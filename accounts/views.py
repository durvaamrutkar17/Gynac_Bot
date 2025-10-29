import os
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt
from home.models import PatientReport
import PyPDF2
import io

def signup_view(request):
    if request.method == "POST":
        username = request.POST["username"]
        email = request.POST["email"]
        password = request.POST["password"]

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists")
            return redirect("signup")

        user = User.objects.create_user(username=username, email=email, password=password)
        user.save()
        messages.success(request, "Account created successfully! Please log in.")
        return redirect("login")

    return render(request, "signup.html")

@csrf_exempt
def login_view(request):
    if request.user.is_authenticated:  
        return redirect('/main/')   # Always redirect if already logged in
       
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            latest_report = PatientReport.objects.filter(user=request.user).first()

            language = None
            if latest_report is not None:
                language = latest_report.data.get("language")

            if language is not None:
                return redirect("/main/")
            else:
                return redirect("/main/details")
        else:
            messages.error(request, "Invalid username or password")
            return redirect("login")
    return render(request, "login.html")

@csrf_exempt
def details(request):
    if request.method == "POST":
        preg_details = request.POST["pregnancy_details"]
        file = request.FILES.get("report")
        
        extracted_text = ""
        if file:
            try:
                file_extension = os.path.splitext(file.name)[1].lower()

                if file_extension == '.pdf':
                    reader = PyPDF2.PdfReader(io.BytesIO(file.read()))
                    for page_num in range(len(reader.pages)):
                        page = reader.pages[page_num]
                        extracted_text += page.extract_text() + "\n"
                elif file_extension in ['.png', '.jpg', '.jpeg']:
                    extracted_text = "Image files cannot be processed for text extraction without OCR libraries (e.g., pytesseract). File uploaded but text not extracted."
                    print("Warning: Image file uploaded but text extraction is not supported with current configuration.")
                else:
                    extracted_text = f"Unsupported file type: {file_extension}. File uploaded but text not extracted."
                    print(f"Warning: Unsupported file type '{file_extension}' uploaded. Text extraction is not supported.")

                report = PatientReport.objects.create(
                name=request.user,
                age=0,
                symptoms=extracted_text,
                )
                return redirect("/main/")

            except Exception as e:
                extracted_text = f"Error processing file: {e}"
                print(f"File processing error: {e}")
    
    return render(request, "details.html")

def logout_view(request):
    logout(request)
    return redirect("login")

def home(request):
    if request.user.is_authenticated:
        return redirect('/main/')  # already logged in → go to chatbot
    return render(request, 'auth.html')