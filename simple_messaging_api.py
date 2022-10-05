# pylint: disable=line-too-long, no-member

from __future__ import print_function

import importlib
import json

import requests

from azure.communication.sms import SmsClient

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from simple_messaging.models import IncomingMessage, OutgoingMessage, encrypt_value

def process_outgoing_message(outgoing_message, metadata=None): # pylint: disable=too-many-branches
    if metadata is None:
        metadata = {}

    azure_connection_string = metadata.get('connection_string', None)

    if azure_connection_string is None:
        if hasattr(settings, 'AZURE_MESSAGING_CONNECTION_STRING'):
            azure_connection_string = settings.AZURE_MESSAGING_CONNECTION_STRING
        else:
            return None
    else:
        del metadata['connection_string']

    azure_phone_number = metadata.get('phone_number', None)

    if azure_phone_number is None:
        if hasattr(settings, 'AZURE_MESSAGING_PHONE_NUMBER'):
            azure_phone_number = settings.AZURE_MESSAGING_PHONE_NUMBER
        else:
            return None
    else:
        del metadata['phone_number']

    azure_enable_delivery_report = metadata.get('enable_delivery_report', None)

    if azure_enable_delivery_report is None and hasattr(settings, 'AZURE_MESSAGING_ENABLE_DELIVERY_REPORT'):
        azure_enable_delivery_report = settings.AZURE_MESSAGING_ENABLE_DELIVERY_REPORT
    else:
        del metadata['enable_delivery_report']

    transmission_metadata = {}

    if (azure_connection_string is not None) and (azure_phone_number is not None) and (azure_enable_delivery_report is not None):
        sms_client = SmsClient.from_connection_string(azure_connection_string)

        if outgoing_message.transmission_metadata is not None:
            transmission_metadata = json.loads(outgoing_message.transmission_metadata)

        if outgoing_message.message.startswith('image:'):
            pass
        else:
            message = outgoing_message.fetch_message(transmission_metadata)

            sms_responses = sms_client.send(from_=azure_phone_number, to=outgoing_message.current_destination(), message=message, enable_delivery_report=azure_enable_delivery_report)

            for result in sms_responses:
                transmission_metadata['azure_message_id'] = result.message_id
                transmission_metadata['azure_successful'] = result.successful
                transmission_metadata['azure_error_message'] = result.error_message

        return transmission_metadata

    return None

def process_incoming_request(request): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    if request.method == 'POST': # pylint: disable=too-many-nested-blocks
        try:
            events = json.loads(request.body)

            is_azure = False

            for event in events:
                if event['eventType'] in ('Microsoft.Communication.SMSReceived', 'Microsoft.Communication.SMSDeliveryReportReceived',):
                    is_azure = True

            if is_azure:
                response_payload = {}

                for event in events:
                    if 'validationCode' in event['data']:
                        response_payload['validationResponse'] = event['data']['validationCode']

                    if 'validationUrl' in event['data']:
                        requests.get(event['data']['validationUrl'], timeout=120)

                    if event['eventType'] == 'Microsoft.Communication.SMSReceived':
                        responses = []

                        for app in settings.INSTALLED_APPS:
                            try:
                                response_module = importlib.import_module('.simple_messaging_api', package=app)

                                responses.extend(response_module.simple_messaging_response(event))
                            except ImportError:
                                pass
                            except AttributeError:
                                pass

                        record_responses = True

                        for app in settings.INSTALLED_APPS:
                            try:
                                response_module = importlib.import_module('.simple_messaging_api', package=app)

                                record_responses = response_module.simple_messaging_record_response(event)
                            except ImportError:
                                pass
                            except AttributeError:
                                pass


                        if record_responses:
                            now = timezone.now()

                            destination = event['data']['to']
                            sender = event['data']['from']

                            incoming = IncomingMessage(recipient=destination, sender=sender)
                            incoming.receive_date = now
                            incoming.message = event['data']['message']

                            if hasattr(settings, 'SIMPLE_MESSAGING_SECRET_KEY'):
                                event['subject'] = encrypt_value(event['subject'])
                                event['data']['to'] = encrypt_value(event['data']['to'])
                                event['data']['from'] = encrypt_value(event['data']['from'])

                            incoming.transmission_metadata = json.dumps(event, indent=2)

                            incoming.save()

                            incoming.encrypt_sender()

                            # Note - no MMS support at the moment (2021-10-04)

                            for app in settings.INSTALLED_APPS:
                                try:
                                    response_module = importlib.import_module('.simple_messaging_api', package=app)

                                    response_module.process_incoming_message(incoming)
                                except ImportError:
                                    pass
                                except AttributeError:
                                    pass

                    elif event['eventType'] == 'Microsoft.Communication.SMSDeliveryReportReceived':
                        message_id = event['data']['messageId']
                        data = event['data']

                        match = OutgoingMessage.objects.filter(transmission_metadata__icontains=message_id).first()

                        if match is not None:
                            metadata = json.loads(match.transmission_metadata)

                            if hasattr(settings, 'SIMPLE_MESSAGING_SECRET_KEY'):
                                data['to'] = encrypt_value(data['to'])
                                data['from'] = encrypt_value(data['from'])

                            metadata['azure_delivery_report'] = data

                            if metadata['azure_delivery_report'].get('deliveryStatus', 'Unknown') != 'Delivered': # pylint: disable=simplifiable-if-statement
                                match.errored = True
                            else:
                                match.errored = False

                            match.transmission_metadata = json.dumps(metadata, indent=2)
                            match.save()

                        match = IncomingMessage.objects.filter(transmission_metadata__icontains=message_id).first()

                        if match is not None:
                            metadata = json.loads(match.transmission_metadata)

                            if hasattr(settings, 'SIMPLE_MESSAGING_SECRET_KEY'):
                                data['to'] = encrypt_value(data['to'])
                                data['from'] = encrypt_value(data['from'])

                            metadata['azure_delivery_report'] = data

                            match.transmission_metadata = json.dumps(metadata, indent=2)
                            match.save()
                    else:
                        print('Unknown event type: ' + event['eventType'])

                    return HttpResponse(json.dumps(response_payload, indent=2), content_type='application/json')
        except json.JSONDecodeError:
            return None

    return None
