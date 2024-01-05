from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import logging
from .models import PhoneNumber, Arm, ScheduledMessage, TextMessage, Topic
from .helper_functions import *
from datetime import datetime, timezone
from django.utils import timezone
from django.db import models
timezone.localtime(timezone.now())
import json
import csv
import traceback
logger = logging.getLogger(__name__)

# Create your views here.
from django.http import HttpResponse, JsonResponse
import vonage
client = vonage.Client(key=settings.VONAGE_KEY, secret=settings.VONAGE_SECRET, timeout=10)
sms = vonage.Sms(client)

@login_required
def home(request):
    return render(request, 'base/home.html')

@csrf_exempt
def inbound_message(request):
    if request.method == 'POST':
        try:
            # Parse JSON data from the request body
            data = json.loads(request.body)
            from_number = data.get('msisdn')  # Sender's phone number
            to_number = data.get('to')         # Receiver's Plivo number
            received_text = data.get('text')
            
            

            default_arm = Arm.objects.get(name__iexact="others")  # Replace 1 with the ID of the default arm
            phone_number, _ = PhoneNumber.objects.get_or_create(phone_number=from_number, defaults={'arm': default_arm})
            logger.info(f"Message received: {phone_number.id}, {to_number}, {received_text}")
            TextMessage.objects.create(phone_number=phone_number, message=received_text, route="incoming")
            if received_text.strip().lower() in ["heart", "corazón", "yes"] and not phone_number.opted_in:
                # phone_number.opted_in = True
                # phone_number.save()
                if received_text.strip().lower() in ["heart", "yes"]:
                    response = "Thank you for opting for this study. The team is working on setting you up. You will receive a welcome message as soon as you are set up."
                if received_text.strip().lower() == "corazón":
                    response = "Gracias por optar por este estudio. El equipo está trabajando para configurarlo. Recibirá un mensaje de bienvenida tan pronto como esté configurado."
                    phone_number.language = "es"
                success = retry_send_message_vonage(response, phone_number, route='outgoing_opt_in')
                TextMessage.objects.create(phone_number=phone_number, message=response, route='outgoing_opt_in')
                phone_number, _ = PhoneNumber.objects.get_or_create(phone_number="17204001070", defaults={'arm': default_arm})
                response = f"New number opted in: {from_number}"
                success = retry_send_message_vonage(response, phone_number, route='outgoing_opt_in')
                TextMessage.objects.create(phone_number=phone_number, message=response, route='outgoing_opt_in')
                if success:
                    return JsonResponse({"response": response}, status=200)
                    
            arm_name = phone_number.arm.name
            logger.info(f"Arm name: {arm_name}")
            if arm_name.lower() == "others":
                response = "Thank you for your interest in Chat 4 Heart Health! As of right now, you are doing well managing your health so we won't be sending you text messages. If your health care provider suggests you could benefit from our program, we'll start sending you text messages to support healthy behavior. Thanks, and have a great day."
                success = retry_send_message_vonage(response, phone_number, route='outgoing_other_arm')
                if success:
                    TextMessage.objects.create(phone_number=phone_number, message=response, route='outgoing_other_arm')
                    return JsonResponse({"response": response}, status=200)
            
            if not phone_number.active or arm_name.lower() == "control":
                return JsonResponse({}, status=200)
            # text_message = TextMessage.objects.create(phone_number=phone_number, message=received_text, route="incoming")
            cleaned_text, text_type = clean_and_determine_text_number_or_stop(received_text)
            response, numbered_dialog, numbered_intents_dict, language, context = generate_response(cleaned_text, text_type, phone_number)
            if numbered_dialog != "":
                response = response + '\n\n' + numbered_dialog
            success = retry_send_message_vonage(response, phone_number, route='outgoing_selection_'+context)
            if success:
                # Message sent successfully
                TextMessage.objects.create(phone_number=phone_number, message=response, route='outgoing_selection_'+context)
                return JsonResponse({"response": response}, status=200)
            else:
                # All retry attempts failed
                return JsonResponse({'error': 'Failed to send message'}, status=500)
        except json.JSONDecodeError as e:
            # Handle JSON decoding error
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    else:
        # Handle other HTTP methods (e.g., GET) if needed
        return JsonResponse({'error': 'Method not allowed'}, status=405)
