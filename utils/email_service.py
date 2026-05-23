"""
Email service using Google SMTP for sending transactional emails.
This module provides a reusable service for sending emails via Google's SMTP servers,
supporting both Gmail and Google Workspace accounts.
"""

import logging
import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Union

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from utils.aws_utils import is_running_on_lambda
logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending transactional emails using AWS SES.
    Supports both synchronous and asynchronous email sending.
    """

    @staticmethod
    def _get_ses_client():
        """
        Create and return an AWS SES client using credentials from settings.
        
        Returns:
            boto3.client: Configured SES client
        """
        return boto3.client(
            'ses',
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY,
            region_name=getattr(settings, 'AWS_SES_REGION', 'ap-northeast-2')
        )

    @staticmethod
    def send_email(
        subject: str,
        recipients: Union[str, List[str]],
        text_content: str,
        html_content: Optional[str] = None,
        sender: Optional[str] = None,
        async_send: bool = True,
        reply_to: Optional[str] = None,
    ) -> bool:
        """
        Send an email using AWS SES.
        
        Args:
            subject: Email subject
            recipients: Single recipient email or list of recipient emails
            text_content: Plain text content of the email
            html_content: HTML content of the email (optional)
            sender: Sender email (falls back to DEFAULT_FROM_EMAIL if not provided)
            async_send: Whether to send the email asynchronously
            reply_to: Reply-to email address (optional)
            
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        try:
            if not isinstance(recipients, list):
                recipients = [recipients]
                
            from_email = sender or settings.DEFAULT_FROM_EMAIL
            
            # Prepare email message
            message = {
                'Subject': {'Data': subject},
                'Body': {
                    'Text': {'Data': text_content}
                }
            }
            
            if html_content:
                message['Body']['Html'] = {'Data': html_content}
            
            # Prepare SES parameters
            ses_params = {
                'Source': from_email,
                'Destination': {
                    'ToAddresses': recipients
                },
                'Message': message
            }
            
            if reply_to:
                ses_params['ReplyToAddresses'] = [reply_to]
            
            if async_send and not is_running_on_lambda():
                # Send email in a separate thread to avoid blocking the request
                threading.Thread(
                    target=EmailService._send_ses_email_thread, 
                    args=(ses_params,)
                ).start()
                return True
            else:
                return EmailService._send_ses_email(ses_params)
                
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False
    
    @staticmethod
    def _send_ses_email(ses_params: dict) -> bool:
        """
        Send email using AWS SES.
        
        Args:
            ses_params: Parameters for SES SendEmail API
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            client = EmailService._get_ses_client()
            response = client.send_email(**ses_params)
            logger.info(f"Email sent! Message ID: {response['MessageId']}")
            return True
        except ClientError as e:
            logger.error(f"Failed to send email via SES: {str(e)}")
            return False
    
    @staticmethod
    def _send_ses_email_thread(ses_params: dict) -> None:
        """
        Helper method to send email via SES in a separate thread.
        
        Args:
            ses_params: Parameters for SES SendEmail API
        """
        try:
            EmailService._send_ses_email(ses_params)
        except Exception as e:
            logger.error(f"Failed to send email in thread: {str(e)}")
    
    @staticmethod
    def _send_mail_thread(email: EmailMultiAlternatives) -> None:
        """
        Helper method to send email in a separate thread.
        
        Args:
            email: Prepared EmailMultiAlternatives object
        """
        try:
            email.send()
        except Exception as e:
            logger.error(f"Failed to send email in thread: {str(e)}")
    
    @staticmethod
    def send_template_email(
        subject: str,
        recipients: Union[str, List[str]],
        template_name: str,
        context: dict,
        sender: Optional[str] = None,
        async_send: bool = True,
        reply_to: Optional[str] = None,
        language: str = 'ko',
    ) -> bool:
        """
        Send an email using a Django template.
        
        Args:
            subject: Email subject
            recipients: Single recipient email or list of recipient emails
            template_name: Name of the template (without extension)
            context: Context data for the template
            sender: Sender email (falls back to DEFAULT_FROM_EMAIL if not provided)
            async_send: Whether to send the email asynchronously
            reply_to: Reply-to email address (optional)
            language: Language code ('ko' or 'en') to determine which template to use
            
        Returns:
            bool: True if the email was sent successfully, False otherwise
        """
        try:
            # Use language-specific template if available
            language_suffix = f"_{language}" if language == 'en' else ""
            
            # Get plain text and HTML content from templates
            text_template = f"emails/{template_name}{language_suffix}.txt"
            html_template = f"emails/{template_name}{language_suffix}.html"
            
            text_content = render_to_string(text_template, context)
            
            # HTML content is optional
            html_content = None
            try:
                html_content = render_to_string(html_template, context)
            except Exception as e:
                logger.warning(f"HTML template {html_template} not found: {str(e)}")
                
                # Fall back to default template if language-specific one not found
                if language == 'en':
                    default_html_template = f"emails/{template_name}.html"
                    try:
                        html_content = render_to_string(default_html_template, context)
                    except Exception:
                        pass
            
            # Adjust subject based on language
            localized_subject = subject
            if language == 'en' and subject == "Welcome to Essentory":
                localized_subject = "Welcome to Essentory"
            elif language == 'en' and subject == "Your Essentory Password Has Been Changed":
                localized_subject = "Your Essentory Password Has Been Changed"
            elif language == 'en' and subject == "Password reset code":
                localized_subject = "Password Reset Code"
            elif language == 'en' and subject == "Email verification code":
                localized_subject = "Email Verification Code"
            
            return EmailService.send_email(
                subject=localized_subject,
                recipients=recipients,
                text_content=text_content,
                html_content=html_content,
                sender=sender,
                async_send=async_send,
                reply_to=reply_to,
            )
            
        except Exception as e:
            logger.error(f"Failed to send template email: {str(e)}")
            return False
    
    @staticmethod
    def test_smtp_connection() -> bool:
        """
        Test the AWS SES connection to verify credentials and connectivity.
        This can be used during startup to validate email configuration.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            client = EmailService._get_ses_client()
            response = client.get_send_quota()
            
            logger.info(f"AWS SES connection test successful. Daily quota: {response['Max24HourSend']}")
            return True
            
        except Exception as e:
            logger.error(f"AWS SES connection test failed: {str(e)}")
            return False