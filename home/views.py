import json
import re
import openai
import time
from django.shortcuts import render, redirect
from django.http import JsonResponse
import PyPDF2
import io
import os
from dotenv import load_dotenv
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import requests
from .models import PatientReport, ChatMessage

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

# ========================================================================
# ===== HELPER FUNCTION TO AVOID CODE DUPLICATION ========================
# ========================================================================
def _get_medication_suggestion(report_data):
    """Calls the AI with a specific prompt for medication suggestions based on a report's data dictionary."""
    if not report_data:
        return "I need a report to be uploaded before I can suggest medications."

    report_content = ""
    # Construct content based on report type
    if report_data.get('type') == 'pregnancy':
        if report_data.get('months'):
            report_content += f"Pregnancy Month: {report_data.get('months')}\n\n"
        if report_data.get('user_details'):
            report_content += f"User Provided Details: {report_data.get('user_details')}\n\n"
        if report_data.get('extracted_main_report_content'):
            report_content += f"--- Main Report Content ---\n{report_data.get('extracted_main_report_content')}\n\n"
        if report_data.get('extracted_blood_report_content'):
            report_content += f"--- Blood Report Content ---\n{report_data.get('extracted_blood_report_content')}\n\n"
    else:  # General report
        report_content = report_data.get('original_content', '')

    if not report_content.strip():
        return "The provided report appears to be empty. I cannot suggest medications based on it."

    try:
        system_message = "You are a gynecology assistant. Provide helpful medication info."
        user_prompt = (f"Based on the following comprehensive report, what are some potential medication suggestions? This is not medical advice and a doctor should always be consulted.\n\n"
                       f"{report_content}")
        response = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role": "system", "content": system_message}, {"role": "user", "content": user_prompt}])
        response_content = response["choices"][0]["message"]["content"]
        # Remove special characters
        cleaned_response = re.sub(r"[\*\&\%\-\,\#]+", " ", response_content)
        return cleaned_response
    except Exception as e:
        return f"An error occurred while generating medication suggestions: {e}"
# ========================================================================

# The ensure_session_initialized function is no longer needed and can be removed.

@login_required
def home(request):
    """Renders the main chat page."""
    return render(request, "index.html")

@login_required
@csrf_exempt
def pregnancy_details_view(request):
    """
    Handles the post-login pregnancy report form.
    If a report already exists for the user, it redirects them to the main chat page.
    NOTE: For the best user experience, set LOGIN_REDIRECT_URL = '/main/details/' in your settings.py.
    This will automatically route new users or users without reports here after login.
    """
    if request.method == "GET":
        # if PatientReport.objects.filter(user=request.user).exists():
        #     return redirect('home')
        return render(request, 'details.html')

    if request.method == "POST":
        report_file = request.FILES.get("report")
        blood_report_file = request.FILES.get("blood_report")
        months = request.POST.get("months")
        pregnancy_details_from_user = request.POST.get("pregnancy_details", "")
        
        extracted_text_from_pdf = ""
        if report_file:
            try:
                if report_file.name.endswith('.pdf'):
                    reader = PyPDF2.PdfReader(io.BytesIO(report_file.read()))
                    extracted_text_from_pdf = "\n".join(page.extract_text() for page in reader.pages)
                else: extracted_text_from_pdf = "Uploaded file was not a PDF for the main report."
            except Exception as e: extracted_text_from_pdf = f"Error processing main report PDF file: {e}"

        extracted_text_from_blood_report = ""
        if blood_report_file:
            try:
                if blood_report_file.name.endswith('.pdf'):
                    reader = PyPDF2.PdfReader(io.BytesIO(blood_report_file.read()))
                    extracted_text_from_blood_report = "\n".join(page.extract_text() for page in reader.pages)
                else: extracted_text_from_blood_report = "Uploaded file was not a PDF for the blood report."
            except Exception as e: extracted_text_from_blood_report = f"Error processing blood report PDF file: {e}"

        initial_analysis_content = ""
        if months: initial_analysis_content += f"Pregnancy Month: {months}\n\n"
        if pregnancy_details_from_user: initial_analysis_content += f"User Provided Pregnancy Details:\n{pregnancy_details_from_user}\n\n"
        initial_analysis_content += f"--- Extracted Main Report Content ---\n{extracted_text_from_pdf.strip()}\n\n"
        initial_analysis_content += f"--- Extracted Blood Report Content ---\n{extracted_text_from_blood_report.strip()}"

        cleaned_response = "Could not generate AI analysis."
        try:
            prompt_for_ai = f'''You are an obstetrics assistant. Summarize the key findings, concerns, and next steps from the following report. 
            Consider the pregnancy month, user's provided details, and both main and blood reports.\n\n
            --- COMPREHENSIVE REPORT ---\n{initial_analysis_content}
            Give summary PRECISELY'''
            response = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt_for_ai}])
            ai_analysis = response["choices"][0]["message"]["content"]
            cleaned_response = re.sub(r"[\*\&\%\-\,\#]+", " ", ai_analysis)
        except Exception as e: cleaned_response = f"An error occurred during analysis: {e}"

        report_data = {
            "type": "pregnancy", "months": months, "user_details": pregnancy_details_from_user,
            "extracted_main_report_content": extracted_text_from_pdf, "extracted_blood_report_content": extracted_text_from_blood_report,
            "analysis": cleaned_response
        }
        PatientReport.objects.create(user=request.user, data=report_data)
        
        bot_message_content = f"Thank you. I have analyzed your report. Here is a summary:\n\n{cleaned_response}\n\nYou can now ask me specific questions about it."
        ChatMessage.objects.create(user=request.user, role='bot', content=bot_message_content)

        return redirect('home')
    return render(request, 'details.html') # Fallback for GET request

@login_required
@csrf_exempt
def chat(request):
    """Handles real-time chat messages, now backed by the database."""
    user_input = request.GET.get("message", "")
    if not user_input:
        return JsonResponse({"reply": "No message provided."}, status=400)

    ChatMessage.objects.create(user=request.user, role='user', content=user_input)
    normalized_input = user_input.lower().strip()
    latest_report_obj = PatientReport.objects.filter(user=request.user).first()
    latest_report_data = latest_report_obj.data if latest_report_obj else None

    # COMMAND INTERCEPTION
    if 'analyze' in normalized_input or 'summary' in normalized_input or 'summarize' in normalized_input:
        if latest_report_data:
            reply = latest_report_data.get('analysis') or latest_report_data.get('summary', "I couldn't find a pre-computed summary for this report.")
        else:
            reply = "I can't analyze a report because you haven't uploaded one yet."
        ChatMessage.objects.create(user=request.user, role='bot', content=reply)
        return JsonResponse({"reply": reply})

    elif 'medication' in normalized_input:
        reply = _get_medication_suggestion(latest_report_data)
        ChatMessage.objects.create(user=request.user, role='bot', content=reply)
        return JsonResponse({"reply": reply})

    # CONTEXT-AWARE Q&A
    context = latest_report_data.get('type') if latest_report_data else 'general'
    system_prompt = "You are a general gynecology assistant bot."

    if context == 'pregnancy' and latest_report_data:
        system_prompt = f"""
You are a medical AI assistant specializing in obstetrics. Your ONLY source of truth is the patient information below. Do not use external knowledge.
--- PATIENT CONTEXT ---
[Pregnancy Month]: {latest_report_data.get('months', 'Not provided.')}
[User-Provided Pregnancy Details]: {latest_report_data.get('user_details', 'Not provided.')}
[Extracted Main Report Content]: {latest_report_data.get('extracted_main_report_content', 'Could not be extracted.')}
[Extracted Blood Report Content]: {latest_report_data.get('extracted_blood_report_content', 'Could not be extracted.')}
--- YOUR INSTRUCTIONS ---
1. Base all answers STRICTLY on the text in the PATIENT CONTEXT.
2. Prioritize the [User-Provided Pregnancy Details] and [Pregnancy Month] as they are direct user input.
3. If the answer is not explicitly found in the PATIENT CONTEXT, you MUST reply as a GENERAL EMPATHY GYNAE BOT which answers MORE EMOTIONALLY.
4. You MUST answer PRECISELY.
"""

    messages_for_openai = [{"role": "system", "content": system_prompt.strip()}, {"role": "user", "content": user_input}]

    try:
        response = openai.ChatCompletion.create(model="gpt-4o-mini", messages=messages_for_openai)
        reply = response["choices"][0]["message"]["content"]
        cleaned_response = re.sub(r"[\*\&\%\-\,\#]+", " ", reply)
    except Exception as e:
        cleaned_response = f"An unexpected error occurred: {e}"

    ChatMessage.objects.create(user=request.user, role='bot', content=cleaned_response)
    return JsonResponse({"reply": cleaned_response})

@login_required
@csrf_exempt
def analyze_session_report(request):
    """Handles the 'Get Summary' and 'Get Medication' buttons using DB data."""
    if request.method == "GET":
        trigger_type = request.GET.get("trigger", "")
        latest_report_obj = PatientReport.objects.filter(user=request.user).first()
        latest_report_data = latest_report_obj.data if latest_report_obj else None

        if not latest_report_data:
            return JsonResponse({"reply": "No report found for your account."}, status=404)

        if trigger_type == "summary":
            reply = latest_report_data.get('analysis') or latest_report_data.get('summary', 'No summary available.')
            return JsonResponse({"reply": reply})
        elif trigger_type == "medication":
            reply = _get_medication_suggestion(latest_report_data)
            return JsonResponse({"reply": reply})
        else:
            return JsonResponse({"reply": "Invalid analysis trigger type."}, status=400)
    return JsonResponse({"status": "Invalid request method"}, status=405)

@login_required
@csrf_exempt
def get_chat_history(request):
    """Retrieves the user's entire chat history from the database."""
    messages = ChatMessage.objects.filter(user=request.user).order_by('timestamp')
    history = [{'who': msg.role, 'text': msg.content} for msg in messages]
    return JsonResponse({"history": history})

@login_required
@csrf_exempt
def clear_all_chat_history(request):
    """Deletes all reports and chat messages for the logged-in user."""
    if request.method == "POST":
        PatientReport.objects.filter(user=request.user).delete()
        ChatMessage.objects.filter(user=request.user).delete()
        return JsonResponse({"status": "New chat started. All your previous reports and messages have been cleared."})
    return JsonResponse({"status": "Invalid request method"}, status=405)

@login_required
@csrf_exempt
def save_report(request):
    """Saves a general report to the database."""
    if request.method == "POST":
        name, age = request.POST["name"], request.POST["age"]
        symptoms_from_form = request.POST.get("symptoms", "")
        file = request.FILES.get("report_file")
        extracted_text = ""
        if file:
            try:
                if file.name.endswith('.pdf'):
                    reader = PyPDF2.PdfReader(io.BytesIO(file.read()))
                    extracted_text = "\n".join(page.extract_text() for page in reader.pages)
                else: extracted_text = "Uploaded file not a PDF."
            except Exception as e: extracted_text = f"Error processing file: {e}"
        final_content = f"Symptoms: {symptoms_from_form}\n\n--- Report Content ---\n{extracted_text.strip()}"
        
        cleaned_response = "Could not generate summary."
        try:
            summary_prompt = f"Summarize patient info into 3-4 key bullet points.\nPatient: {name}, Age: {age}\nDetails:\n{final_content}"
            response = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role": "user", "content": summary_prompt}])
            summary = response["choices"][0]["message"]["content"]
            cleaned_response = re.sub(r"[\*\&\%\-\,\#]+", " ", summary)
        except Exception: pass
        
        report_data = {"type": "general", "name": name, "age": age, "original_content": final_content, "summary": cleaned_response}
        new_report = PatientReport.objects.create(user=request.user, data=report_data)
        
        return JsonResponse({"status": "Report processed!", "report_id": new_report.pk, "summary": cleaned_response})
    return JsonResponse({"status": "Invalid request"}, status=405)

@csrf_exempt
def localAnalyze(request):
    # This view does not depend on user session data and remains unchanged.
    if request.method == "POST":
        try:
            symptoms_text = json.loads(request.body).get("symptoms", "")
            prompt = f'Analyze symptoms and return JSON strictly: {{ "severity": "high" | "low", "suggestions": [ "string" ] }}\n\nSymptoms: "{symptoms_text}"'
            response = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.2)
            result = json.loads(response["choices"][0]["message"]["content"])
            # The original code here was incorrect (re.sub on a dict). Assuming you want to clean strings within the dict.
            # This part is left as is, as it's outside the scope of the persistence request.
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"error": "Only POST allowed"}, status=405)
