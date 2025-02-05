from django.conf import settings
import random
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException


def send_otp(recipient_email,recipient_name,otp,template_id=3):
    # Configure API key authorization: api-key
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = settings.BREVO_API_KEY

    # create an instance of the API class
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_email,"name": recipient_name}],
        template_id=template_id,
        params={"otp":otp,"name":recipient_name}, 
        headers={"X-Mailin-custom": "custom_header_1:custom_value_1|custom_header_2:custom_value_2|custom_header_3:custom_value_3", "charset": "iso-8859-1"}) # SendSmtpEmail | Values to send a transactional email



    try:
        # Send a transactional email
        api_response = api_instance.send_transac_email(send_smtp_email)
        if api_response.message_id:
            return True
        else:
            return False
    except ApiException as e:
        return False
    

def genereat_otp(digit=6):
    return random.randint(10**(digit-1), 10**digit-1)
