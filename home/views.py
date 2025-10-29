import base64
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
import PyPDF2
import io
import traceback

from PIL import Image as PilImage  # kept for completeness
from .models import PatientReport, ChatMessage, DailyLog

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

_RED_FLAG_KEYWORDS = [
    "no movement", "less movement", "not moving", "haven't felt the baby",
    "bleeding", "spotting", "gush of fluid", "water broke",
    "severe headache", "blurry vision", "seeing spots",
    "intense pain", "severe cramp", "unbearable pain", "constant contraction"
]

# ------------------------------
# CORE VIEWS (preserved)
# ------------------------------
@csrf_exempt
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
    HYBRID form: structured data + file uploads.
    """
    if request.method == "POST":
        # === STEP 1: FORM DATA ===
        form_data = {
            "dob": request.POST.get("dob"),
            "phone": request.POST.get("phone"),
            "language": request.POST.get("language"),
            "location": {"city": request.POST.get("city"), "pincode": request.POST.get("pincode")},
            "lmp": request.POST.get("lmp"),
            "dueDate": request.POST.get("dueDate"),
            "multiplePregnancy": request.POST.get("multiplePregnancy"),
            "doctorName": request.POST.get("doctorName"),
            "hospitalName": request.POST.get("hospitalName"),
            "emergencyContact": {
                "name": request.POST.get("emergencyContactName"),
                "phone": request.POST.get("emergencyContactPhone")
            },
            "gpal": {
                "g": request.POST.get("gpal_g"),
                "p": request.POST.get("gpal_p"),
                "a": request.POST.get("gpal_a"),
                "l": request.POST.get("gpal_l")
            },
            "previousCSection": True if request.POST.get("previousCSection") == "on" else False,
            "conditions": {
                "diabetes": True if request.POST.get("condition_diabetes") == "on" else False,
                "hypertension": True if request.POST.get("condition_hypertension") == "on" else False,
                "thyroid": True if request.POST.get("condition_thyroid") == "on" else False,
                "pcos": True if request.POST.get("condition_pcos") == "on" else False,
                "anemia": True if request.POST.get("condition_anemia") == "on" else False,
            },
            "allergies": {"drug": request.POST.get("drugAllergies"), "food": request.POST.get("foodAllergies")},
            "lifestyle": {
                "diet": request.POST.get("diet"),
                "activityLevel": request.POST.get("activityLevel"),
                "sleepHours": request.POST.get("sleepHours"),
                "stressLevel": request.POST.get("stressLevel")
            },
            "vitals": {
                "prePregnancyWeight": request.POST.get("prePregnancyWeight"),
                "currentWeight": request.POST.get("currentWeight"),
                "height": request.POST.get("height")
            }
        }

        weeks_pregnant = "Not calculated"
        if form_data.get("lmp"):
            try:
                lmp_date = datetime.strptime(form_data["lmp"], "%Y-%m-%d").date()
                delta = date.today() - lmp_date
                weeks_pregnant = delta.days // 7
            except (ValueError, TypeError):
                pass
        form_data["weeks_pregnant"] = weeks_pregnant

        # === STEP 2: FILES ===
        sonography_report_file = request.FILES.get("sonographyReport")
        blood_report_file = request.FILES.get("bloodReport")
        
        extracted_text_from_sonography = ""
        if sonography_report_file:
            try:
                reader = PyPDF2.PdfReader(io.BytesIO(sonography_report_file.read()))
                extracted_text_from_sonography = "\n".join(
                    page.extract_text() for page in reader.pages if page.extract_text()
                )
            except Exception as e:
                extracted_text_from_sonography = f"Error processing sonography PDF: {e}"

        extracted_text_from_blood_report = ""
        if blood_report_file:
            try:
                reader = PyPDF2.PdfReader(io.BytesIO(blood_report_file.read()))
                extracted_text_from_blood_report = "\n".join(
                    page.extract_text() for page in reader.pages if page.extract_text()
                )
            except Exception as e:
                extracted_text_from_blood_report = f"Error processing blood report PDF: {e}"

        # === STEP 3: AI ANALYSIS ===
        user_provided_summary = f"""
        - Patient is {weeks_pregnant} weeks pregnant.
        - DOB: {form_data.get('dob')}. Conditions: {', '.join([k for k, v in form_data.get('conditions', {}).items() if v]) or 'None'}.
        - Vitals: Current Weight {form_data.get('vitals', {}).get('currentWeight')}kg, Height {form_data.get('vitals', {}).get('height')}cm.
        - Allergies: Drug: {form_data.get('allergies',{}).get('drug') or 'None'}, Food: {form_data.get('allergies',{}).get('food') or 'None'}.
        """
        cleaned_response = "Could not generate AI analysis."
        try:
            full_context_for_ai = (
                f"### User Profile:\n{user_provided_summary}\n\n"
                f"### Sonography Report Text:\n{extracted_text_from_sonography}\n\n"
                f"### Blood Report Text:\n{extracted_text_from_blood_report}"
            )

            prompt = (
                "Analyze the following patient profile and lab reports. Provide a concise, 2 line summary "
                "highlighting key findings, potential concerns, and topics to discuss with a doctor. "
                "Be empathetic and professional."
            )
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

        # === STEP 4: SAVE ===
        report_data = {
            "type": "pregnancy",
            **form_data,
            "extracted_sonography_report_content": extracted_text_from_sonography,
            "extracted_blood_report_content": extracted_text_from_blood_report,
            "analysis": cleaned_response,
        }
        PatientReport.objects.update_or_create(user=request.user, defaults={'data': report_data})

        bot_message_content = (
            "Thank you for setting up your profile. Based on the information and reports provided, "
            "here is a quick summary:\n\n"
            f"{cleaned_response}\n\nI am now ready to help. How are you feeling today?"
        )
        ChatMessage.objects.filter(user=request.user).delete()  # Clear old messages
        ChatMessage.objects.create(user=request.user, role='bot', content=bot_message_content)

        return redirect('home')

    return render(request, 'details.html')



@login_required
@csrf_exempt
def chat(request):
    user_input = request.GET.get("message", "").strip()
    lang = request.GET.get("lang", "en").strip()

    if not user_input:
        return JsonResponse({"reply": "No message provided."}, status=400)

    # Save user's message
    ChatMessage.objects.create(user=request.user, role='user', content=user_input)

    # --- Red Flag Check (No change here, this is a good safety feature) ---
    normalized_input = user_input.lower()
    for keyword in _RED_FLAG_KEYWORDS:
        if keyword in normalized_input:
            report = PatientReport.objects.filter(user=request.user).first()
            emergency_info = ""
            if report and report.data:
                contact_name = report.data.get("emergencyContact", {}).get("name")
                hospital = report.data.get("hospitalName")
                if hospital:
                    emergency_info += f"\nYour registered hospital is: {hospital}."
                if contact_name:
                    emergency_info += f"\nYour emergency contact is {contact_name}."
            reply = (
                "This could be serious. Please contact your doctor immediately or visit the nearest emergency room. "
                "Your health and your baby's health are the top priority."
                f"{emergency_info}"
            )
            ChatMessage.objects.create(user=request.user, role='bot', content=reply)
            return JsonResponse({"reply": reply, "is_alert": True})

    # --- MODIFIED: Build a much more detailed context from the saved report data ---
    latest_report_obj = PatientReport.objects.filter(user=request.user).first()
    context_summary = "No detailed patient profile available."
    if latest_report_obj and latest_report_obj.data:
        data = latest_report_obj.data
        # Create a list of known conditions
        conditions_list = [k for k, v in data.get('conditions', {}).items() if v]
        conditions_str = ', '.join(conditions_list) or 'None'
        
        # Build the detailed context string
        context_summary = (
            f"- Patient Name: {request.user.get_full_name() or request.user.username}.\n"
            f"- DOB: {data.get('dob', '1-1-2000')}.\n"
            f"- Due Date: {data.get('dueDate', 'Not provided')}.\n"
            f"- Known Medical Conditions: {conditions_str}.\n"
            f"- Previous C-Section: {'Yes' if data.get('previousCSection') else 'No'}.\n"
            f"- Drug Allergies: {data.get('allergies', {}).get('drug', 'None reported')}.\n"
            f"- Food Allergies: {data.get('allergies', {}).get('food', 'None reported')}.\n"
            f"- Doctor's Name: {data.get('doctorName', 'Not provided')}.\n"
            f"- Location: {data.get('location', {}).get('city', 'Not provided')}."
        )

    # --- MODIFIED: New system prompt to force specific advice ---
    system_prompt = (
        f"You are Shrishti.ai, an expert AI pregnancy companion. Your role is to be a supportive and direct advisor. "
        f"Respond in the user's language ({lang}).\n"
        f"You MUST provide specific suggestions when asked for medicine or exercise. Do not refuse or simply say 'consult a doctor.' "
        f"For example, if asked about a headache, suggest 'acetaminophen (Tylenol)'. If asked for exercise, suggest 'prenatal yoga or 30 minutes of daily walking.' "
        f"Always use the patient's data for context.\n\n"
        f"--- Patient Context ---\n"
        f"{context_summary}\n"
        f"--- End Context ---\n"
        f"Your answers should be caring, but direct and concise (2-3 sentences)."
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response["choices"][0]["message"]["content"]
    except Exception as e:
        # It's good practice to log the actual error
        print(f"OpenAI API Error: {e}") 
        reply = "I'm having a little trouble connecting right now. Please try again in a moment."

    # Save bot's reply
    ChatMessage.objects.create(user=request.user, role='bot', content=reply)
    return JsonResponse({"reply": reply})

@login_required
def get_user_profile(request):
    latest_report = PatientReport.objects.filter(user=request.user).first()
    if latest_report and isinstance(latest_report.data, dict):
        profile_data = {"name": request.user.username, **latest_report.data}
        return JsonResponse(profile_data)
    else:
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
            DailyLog.objects.update_or_create(
                user=request.user,
                log_date=date.today(),
                defaults={'data': {'type': 'symptom', 'text': symptom_text}}
            )
            return JsonResponse({"status": "success", "message": "Symptom logged successfully."})
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON."}, status=400)
    return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)


@login_required
@csrf_exempt
def get_chat_history(request):
    messages = ChatMessage.objects.filter(user=request.user).order_by('timestamp')
    history = [{'who': msg.role, 'text': msg.content} for msg in messages]
    if not history and PatientReport.objects.filter(user=request.user).exists():
        history.append({'who': 'bot', 'text': "Welcome back! How can I help you today?"})
    return JsonResponse({"history": history})


@login_required
@csrf_exempt
def clear_all_chat_history(request):
    if request.method == "POST":
        PatientReport.objects.filter(user=request.user).delete()
        ChatMessage.objects.filter(user=request.user).delete()
        DailyLog.objects.filter(user=request.user).delete()
        return JsonResponse({"status": "success", "message": "All user data cleared."})

# =========================================================================
# === GEMINI VISION & AUDIO ===============================================
# =========================================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def gemini(request):
    return render(request, 'geminiBot.html')

@csrf_exempt
def send_frame(request):
    """
    Gemini Vision endpoint.
    - Always expects an image (data URL or raw base64) in "frame".
    - Optionally accepts:
        * "audio": data URL (audio/webm or audio/wav) to ask a spoken question
        * "question": plain text question
    The model will answer ABOUT THIS IMAGE using the provided question (audio or text).
    If neither audio nor text question is given, it returns a brief 1–2 line description.
    """
    if not GEMINI_API_KEY:
        return JsonResponse({"reply": "Error: GEMINI_API_KEY not configured on the server."}, status=500)

    try:
        data = json.loads(request.body or "{}")

        # ---- image ----
        frame = data.get("frame", "")
        if not frame:
            return JsonResponse({"reply": "Missing 'frame'."}, status=400)

        if "," in frame and frame.startswith("data:"):
            header, img_b64 = frame.split(",", 1)
            img_mime = header.split(";")[0].replace("data:", "") or "image/jpeg"
        else:
            img_b64 = frame
            img_mime = data.get("mime_type", "image/jpeg")

        # ---- optional audio question ----
        audio_b64, audio_mime = None, None
        audio = data.get("audio")
        if audio:
            if "," in audio and audio.startswith("data:"):
                aheader, audio_b64 = audio.split(",", 1)
                audio_mime = aheader.split(";")[0].replace("data:", "") or "audio/webm"
            else:
                audio_b64 = audio
                audio_mime = data.get("audio_mime_type", "audio/webm")

        # ---- optional text question ----
        user_q = (data.get("question") or "").strip()

        # ---- prompt ----
        base = (
            "You are Shrishti.ai, an empathetic pregnancy companion.\n"
            "Use the image and any provided user question (audio or text) to answer briefly.\n"
            "- If there IS a user question: answer it in 1 sentences grounded in the image.\n"
            "- If there is NO question: give a 1 line friendly description of what's in the image. Ask Question.\n"
        )

        # ---- build parts ----
        parts = [{"text": base}]
        parts.append({"inline_data": {"mime_type": img_mime, "data": img_b64}})  # image first
        if audio_b64:
            parts.append({"inline_data": {"mime_type": audio_mime, "data": audio_b64}})
        if user_q:
            parts.append({"text": f"User question: {user_q}"})

        GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        url = (
            f"https://generativelanguage.googleapis.com/"
            f"v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        )

        payload = {"contents": [{"role": "user", "parts": parts}]}

        resp = requests.post(url, json=payload, timeout=60)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as http_err:
            extra = ""
            try:
                j = resp.json()
                extra = f" - {j}"
            except Exception:
                pass
            msg = (
                f"HTTP error occurred: {http_err}{extra}\n"
                "Tip: Set GEMINI_MODEL to a listed model (e.g., 'gemini-2.0-flash', 'gemini-2.5-flash-lite'). "
                "Verify via: GET https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY"
            )
            return JsonResponse({"reply": msg}, status=500)

        data_json = resp.json()
        text = (
            data_json.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        if not text:
            return JsonResponse({"reply": "Received response but no text was returned.", "raw": data_json}, status=200)

        return JsonResponse({"reply": text})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"reply": f"Unexpected error: {e}"}, status=500)


@csrf_exempt
def send_audio(request):
    """
    Kept for standalone audio → text use cases (chat/mic card).
    """
    if not GEMINI_API_KEY:
        return JsonResponse({"reply": "Error: GEMINI_API_KEY not configured on the server."}, status=500)

    try:
        data = json.loads(request.body or "{}")
        audio = data.get("audio", "")
        user_hint = (data.get("hint") or "").strip()

        if "," in audio and audio.startswith("data:"):
            header, b64 = audio.split(",", 1)
            mime_type = header.split(";")[0].replace("data:", "") or "audio/webm"
        else:
            b64 = audio
            mime_type = data.get("mime_type", "audio/webm")

        base_prompt = (
            "You are Shrishti.ai, an empathetic pregnancy companion. "
            "Listen to the user's audio. If they asked a question, answer it in 1-2 sentences. "
            "If it's general speech, summarize it in one friendly line and ask a gentle follow-up. "
        )
        if user_hint:
            base_prompt += f"\nUser hint: {user_hint}"

        GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        url = (
            f"https://generativelanguage.googleapis.com/"
            f"v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        )

        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": base_prompt},
                    {"inline_data": {"mime_type": mime_type, "data": b64}}
                ]
            }]
        }

        resp = requests.post(url, json=payload, timeout=60)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as http_err:
            extra = ""
            try:
                j = resp.json()
                extra = f" - {j}"
            except Exception:
                pass
            msg = (
                f"HTTP error occurred: {http_err}{extra}\n"
                "Tip: If you get 404, set GEMINI_MODEL to a listed model "
                "(e.g., 'gemini-2.0-flash' or 'gemini-2.5-flash-lite') and verify with GET /v1beta/models."
            )
            return JsonResponse({"reply": msg}, status=500)

        data_json = resp.json()
        text = (
            data_json.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        if not text:
            return JsonResponse({"reply": "Received response but no text was returned.", "raw": data_json}, status=200)

        return JsonResponse({"reply": text})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"reply": f"Unexpected error: {e}"}, status=500)
