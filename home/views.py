# main/views.py

import json
import re
from datetime import date, datetime
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import requests
import os
from dotenv import load_dotenv
import openai
import PyPDF2  # Ensure PyPDF2 is imported
import io      # Ensure io is imported

from .models import PatientReport, ChatMessage, DailyLog

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")
ANAM_API_KEY = os.getenv("ANAM_API_KEY")

# --- SAFETY FEATURE CONSTANTS ---
_RED_FLAG_KEYWORDS = [
    "no movement", "less movement", "not moving", "haven't felt the baby",
    "bleeding", "spotting", "gush of fluid", "water broke",
    "severe headache", "blurry vision", "seeing spots",
    "intense pain", "severe cramp", "unbearable pain", "constant contraction"
]

@csrf_exempt
def anam_session_token(request):
    url = "https://api.anam.ai/v1/auth/session-token"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {ANAM_API_KEY}"}
    payload = { "personaConfig": { "name": "MyPersona", "avatarId": "30fa96d0-26c4-4e55-94a0-517025942e18", "voiceId": "6bfbe25a-979d-40f3-a92b-5394170af54b", "llmId": "0934d97d-0c3a-4f33-91b0-5e136a0ef466", "systemPrompt": "You are a helpful assistant."}}
    resp = requests.post(url, headers=headers, json=payload)
    return JsonResponse(resp.json(), safe=False)

@login_required
def home(request):
    latest_report = PatientReport.objects.filter(user=request.user).first()

    language = None
    if latest_report is not None:
        language = latest_report.data.get("language")

        if language is not None:
            return render(request, 'index.html')
        else:
            return redirect("/main/details")
    else:
        return redirect("/main/details")


@login_required
@csrf_exempt
def pregnancy_details_view(request):
    """
    Handles the HYBRID form: comprehensive data + file uploads.
    """
    if request.method == "POST":
        # === STEP 1: GATHER ALL STRUCTURED FORM DATA ===
        form_data = {
            "dob": request.POST.get("dob"), "phone": request.POST.get("phone"), "language": request.POST.get("language"),
            "location": {"city": request.POST.get("city"), "pincode": request.POST.get("pincode")},
            "lmp": request.POST.get("lmp"), "dueDate": request.POST.get("dueDate"), "multiplePregnancy": request.POST.get("multiplePregnancy"),
            "doctorName": request.POST.get("doctorName"), "hospitalName": request.POST.get("hospitalName"),
            "emergencyContact": {"name": request.POST.get("emergencyContactName"), "phone": request.POST.get("emergencyContactPhone")},
            "gpal": {"g": request.POST.get("gpal_g"), "p": request.POST.get("gpal_p"), "a": request.POST.get("gpal_a"), "l": request.POST.get("gpal_l")},
            "previousCSection": True if request.POST.get("previousCSection") == "on" else False,
            "conditions": {
                "diabetes": True if request.POST.get("condition_diabetes") == "on" else False,
                "hypertension": True if request.POST.get("condition_hypertension") == "on" else False,
                "thyroid": True if request.POST.get("condition_thyroid") == "on" else False,
                "pcos": True if request.POST.get("condition_pcos") == "on" else False,
                "anemia": True if request.POST.get("condition_anemia") == "on" else False,
            },
            "allergies": {"drug": request.POST.get("drugAllergies"), "food": request.POST.get("foodAllergies")},
            "lifestyle": {"diet": request.POST.get("diet"), "activityLevel": request.POST.get("activityLevel"), "sleepHours": request.POST.get("sleepHours"), "stressLevel": request.POST.get("stressLevel")},
            "vitals": {"prePregnancyWeight": request.POST.get("prePregnancyWeight"), "currentWeight": request.POST.get("currentWeight"), "height": request.POST.get("height")}
        }
        weeks_pregnant = "Not calculated"
        if form_data.get("lmp"):
            try:
                lmp_date = datetime.strptime(form_data["lmp"], "%Y-%m-%d").date()
                delta = date.today() - lmp_date
                weeks_pregnant = delta.days // 7
            except (ValueError, TypeError): pass
        form_data["weeks_pregnant"] = weeks_pregnant

        # === STEP 2: PROCESS UPLOADED FILES (RESTORED LOGIC) ===
        sonography_report_file = request.FILES.get("sonographyReport")
        blood_report_file = request.FILES.get("bloodReport")
        
        extracted_text_from_sonography = ""
        if sonography_report_file:
            try:
                reader = PyPDF2.PdfReader(io.BytesIO(sonography_report_file.read()))
                extracted_text_from_sonography = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
            except Exception as e:
                extracted_text_from_sonography = f"Error processing sonography PDF: {e}"

        extracted_text_from_blood_report = ""
        if blood_report_file:
            try:
                reader = PyPDF2.PdfReader(io.BytesIO(blood_report_file.read()))
                extracted_text_from_blood_report = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
            except Exception as e:
                extracted_text_from_blood_report = f"Error processing blood report PDF: {e}"

        # === STEP 3: GENERATE AI ANALYSIS (RESTORED LOGIC) ===
        # Create a text summary of the user's profile for the AI
        user_provided_summary = f"""
        - Patient is {weeks_pregnant} weeks pregnant.
        - DOB: {form_data.get('dob')}. Conditions: {', '.join([k for k, v in form_data.get('conditions', {}).items() if v]) or 'None'}.
        - Vitals: Current Weight {form_data.get('vitals', {}).get('currentWeight')}kg, Height {form_data.get('vitals', {}).get('height')}cm.
        - Allergies: Drug: {form_data.get('allergies',{}).get('drug') or 'None'}, Food: {form_data.get('allergies',{}).get('food') or 'None'}.
        """
        cleaned_response = "Could not generate AI analysis."
        try:
            full_context_for_ai = (f"### User Profile:\n{user_provided_summary}\n\n"
                                   f"### Sonography Report Text:\n{extracted_text_from_sonography}\n\n"
                                   f"### Blood Report Text:\n{extracted_text_from_blood_report}")

            prompt = ("Analyze the following patient profile and lab reports. Provide a concise, 2-3 line summary highlighting key findings, potential concerns, and topics to discuss with a doctor. Be empathetic and professional.")
            
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert obstetrics assistant AI."},
                    {"role": "user", "content": f"{prompt}\n\n--- DATA ---\n{full_context_for_ai}"}
                ]
            )
            ai_analysis = response["choices"][0]["message"]["content"]
            cleaned_response = re.sub(r"[\*#]+", "", ai_analysis).strip()
        except Exception as e:
            cleaned_response = f"An error occurred during AI analysis: {e}"

        # === STEP 4: SAVE EVERYTHING TO DATABASE ===
        report_data = {
            "type": "pregnancy",
            **form_data,
            "extracted_sonography_report_content": extracted_text_from_sonography,
            "extracted_blood_report_content": extracted_text_from_blood_report,
            "analysis": cleaned_response,
        }
        PatientReport.objects.update_or_create(user=request.user, defaults={'data': report_data})
        
        # Create a welcome message with the analysis
        bot_message_content = f"Thank you for setting up your profile. Based on the information and reports provided, here is a quick summary:\n\n{cleaned_response}\n\nI am now ready to help. How are you feeling today?"
        ChatMessage.objects.filter(user=request.user).delete() # Clear any old messages
        ChatMessage.objects.create(user=request.user, role='bot', content=bot_message_content)

        return redirect('home')

    return render(request, 'details.html')


# ... (The rest of the views.py file remains exactly the same as my previous answer) ...

@login_required
@csrf_exempt
def chat(request):
    user_input = request.GET.get("message", "").strip()
    lang = request.GET.get("lang", "en").strip()

    if not user_input:
        return JsonResponse({"reply": "No message provided."}, status=400)
    ChatMessage.objects.create(user=request.user, role='user', content=user_input)
    normalized_input = user_input.lower()
    for keyword in _RED_FLAG_KEYWORDS:
        if keyword in normalized_input:
            report = PatientReport.objects.filter(user=request.user).first()
            emergency_info = ""
            if report and report.data:
                contact_name = report.data.get("emergencyContact", {}).get("name")
                hospital = report.data.get("hospitalName")
                if hospital: emergency_info += f"\nYour registered hospital is: {hospital}."
                if contact_name: emergency_info += f"\nYour emergency contact is {contact_name}."
            reply = (f"This could be serious. Please contact your doctor immediately or visit the nearest emergency room. Your health and your baby's health are the top priority.{emergency_info}")
            ChatMessage.objects.create(user=request.user, role='bot', content=reply)
            return JsonResponse({"reply": reply, "is_alert": True})
    latest_report_obj = PatientReport.objects.filter(user=request.user).first()
    context_summary = "No detailed profile available."
    if latest_report_obj and latest_report_obj.data:
        data = latest_report_obj.data
        context_summary = f"- Patient is {data.get('weeks_pregnant', 'unknown')} weeks pregnant. - Conditions: {', '.join([k for k, v in data.get('conditions', {}).items() if v]) or 'None'}. "
    system_prompt = f"""You are Shrishti.ai, a friendly and empathetic AI pregnancy companion. You are NOT a doctor.  Respond in {lang}. Always remind the user to consult their doctor for any medical concerns. Use the following context: {context_summary}. Keep answers concise and caring (2-4 sentences). For medical questions, give a general answer and ALWAYS end with 'Please consult your doctor for personalized medical advice.'"""
    try:
        response = openai.ChatCompletion.create(model="gpt-4o-mini", messages=[{"role": "system", "content": system_prompt.strip()}, {"role": "user", "content": user_input}])
        reply = response["choices"][0]["message"]["content"]
    except Exception as e:
        reply = f"I'm having a little trouble connecting right now. Please try again in a moment."
    ChatMessage.objects.create(user=request.user, role='bot', content=reply)
    return JsonResponse({"reply": reply})

@login_required
def get_user_profile(request):
    latest_report = PatientReport.objects.filter(user=request.user).first()
    if latest_report and isinstance(latest_report.data, dict):
        profile_data = {"name": request.user.username, **latest_report.data}
        return JsonResponse(profile_data)
    else:
        # redirect('/main/details')
        return JsonResponse({"error": "No profile data found."}, status=404)

@login_required
@csrf_exempt
def log_symptom(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            symptom_text = data.get("symptom")
            if not symptom_text:
                return JsonResponse({"status": "error", "message": "Symptom text cannot be empty."}, status=400)
            log_entry, created = DailyLog.objects.update_or_create(user=request.user, log_date=date.today(), defaults={'data': {'type': 'symptom', 'text': symptom_text}})
            return JsonResponse({"status": "success", "message": "Symptom logged successfully."})
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON."}, status=400)
    return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)

@login_required
@csrf_exempt
def get_chat_history(request):
    messages = ChatMessage.objects.filter(user=request.user).order_by('timestamp')
    history = [{'who': msg.role, 'text': msg.content} for msg in messages]
    if not history:
        if PatientReport.objects.filter(user=request.user).exists():
             history.append({'who': 'bot', 'text': "Welcome back! How can I help you today?"})
    return JsonResponse({"history": history})

@login_required
@csrf_exempt
def clear_all_chat_history(request):
    if request.method == "POST":
        PatientReport.objects.filter(user=request.user).delete()
        ChatMessage.objects.filter(user=request.user).delete()
        DailyLog.objects.filter(user=request.user).delete()
        return JsonResponse