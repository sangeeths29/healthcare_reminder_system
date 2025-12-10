"""
Healthcare AI Reminder System

The idea is simple: GPT writes friendly reminder messages, but we don't blindly 
trust it. Instead, we have Gemini review each message before sending. Think of 
it like having an editor check a writer's work.

To test: python simple_reminder.py
"""

import os
import asyncio
import httpx
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict
from twilio.rest import Client as TwilioClient


# ============================================================================
# SETTINGS
# Put your API keys here (or use environment variables in production)
# ============================================================================

@dataclass
class Settings:
    """All the configuration in one place - easy to find and change."""
    
    # LLM API keys (set these in your .env file)
    openai_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_key: str = os.getenv("GEMINI_API_KEY", "")
    
    # Twilio credentials (get these from console.twilio.com)
    twilio_account_sid: str = os.getenv("TWILIO_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_TOKEN", "")
    twilio_whatsapp_number: str = os.getenv("TWILIO_WHATSAPP_NUMBER", "")
    
    # Patient info (in a real system, this would come from a database)
    patient_name: str = os.getenv("PATIENT_NAME", "Patient")
    patient_phone: str = os.getenv("PATIENT_PHONE", "")
    
    # Quality threshold - messages scoring below this use the safe fallback
    minimum_quality_score: float = 4.0
    
    def validate(self) -> bool:
        """Check that all required environment variables are set."""
        required = [
            ("OPENAI_API_KEY", self.openai_key),
            ("GEMINI_API_KEY", self.gemini_key),
            ("TWILIO_SID", self.twilio_account_sid),
            ("TWILIO_TOKEN", self.twilio_auth_token),
            ("PATIENT_PHONE", self.patient_phone),
        ]
        missing = [name for name, value in required if not value]
        if missing:
            print(f"❌ Missing required environment variables: {', '.join(missing)}")
            print("   Please copy .env.example to .env and fill in your credentials.")
            return False
        return True


# ============================================================================
# DATA STRUCTURES
# Simple containers for passing data around
# ============================================================================

@dataclass
class Appointment:
    """Everything we need to know about an appointment."""
    patient_name: str
    appointment_type: str
    doctor_name: str
    clinic_location: str
    appointment_time: datetime
    
    def get_formatted_time(self) -> str:
        """Returns something like 'Wednesday, December 11 at 10:00 AM'"""
        return self.appointment_time.strftime("%A, %B %d at %I:%M %p")


@dataclass 
class QualityScores:
    """The scores Gemini gives to a message."""
    completeness: int      # Does it have all the details?
    tone: int              # Is it friendly?
    clarity: int           # Is it easy to understand?
    length: int            # Is it the right length for a text?
    professionalism: int   # Is it appropriate for healthcare?
    feedback: str          # Gemini's explanation
    
    def get_average(self) -> float:
        """Calculate the average of all scores."""
        total = self.completeness + self.tone + self.clarity + self.length + self.professionalism
        return round(total / 5, 2)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "completeness": self.completeness,
            "tone": self.tone,
            "clarity": self.clarity,
            "length": self.length,
            "professionalism": self.professionalism,
            "feedback": self.feedback
        }


@dataclass
class EvaluationResult:
    """The complete result from evaluating a message."""
    scores: QualityScores
    average_score: float
    passed_quality_check: bool
    
    
@dataclass
class ReminderResult:
    """What we return after sending (or trying to send) a reminder."""
    message_sent: str
    evaluation: EvaluationResult
    status: str  # "sent_ai", "sent_fallback", or "failed"


# ============================================================================
# INTERFACES (Abstract Base Classes)
# These define WHAT each component does, not HOW it does it.
# Makes it easy to swap implementations (e.g., use Claude instead of GPT).
# ============================================================================

class MessageWriter(ABC):
    """
    Interface for anything that writes reminder messages.
    
    Right now we use GPT, but you could easily create:
    - ClaudeMessageWriter
    - TemplateMessageWriter  
    - HumanMessageWriter (for comparison testing)
    """
    
    @abstractmethod
    async def write_message(self, appointment: Appointment) -> str:
        """Generate a reminder message for this appointment."""
        pass


class MessageEvaluator(ABC):
    """
    Interface for anything that evaluates message quality.
    
    We use Gemini, but you could create:
    - GPT4Evaluator (though self-evaluation isn't ideal)
    - HumanEvaluator (for ground truth comparison)
    - RuleBasedEvaluator (simple keyword checking)
    """
    
    @abstractmethod
    async def evaluate_message(self, message: str, appointment: Appointment) -> EvaluationResult:
        """Score this message on quality criteria."""
        pass


class MessageSender(ABC):
    """
    Interface for anything that delivers messages.
    
    We use Twilio WhatsApp, but you could create:
    - TwilioSMSSender
    - EmailSender
    - SlackSender
    - MockSender (for testing)
    """
    
    @abstractmethod
    def send_message(self, message: str, recipient: str) -> bool:
        """Send the message. Returns True if successful."""
        pass


# ============================================================================
# IMPLEMENTATIONS
# The actual code that does the work. Each class has one job.
# ============================================================================

class GPTMessageWriter(MessageWriter):
    """
    Uses OpenAI's GPT to write friendly, personalized reminder messages.
    
    We use a high temperature (0.8) so each message is unique - nobody wants 
    to get the exact same text every time.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.model = "gpt-4o-mini"  # Fast and cheap, good enough for reminders
    
    async def write_message(self, appointment: Appointment) -> str:
        prompt = f"""Write a short, friendly WhatsApp reminder for {appointment.patient_name}.

Details:
- Appointment: {appointment.appointment_type}
- When: {appointment.get_formatted_time()}
- Doctor: {appointment.doctor_name}
- Location: {appointment.clinic_location}

Requirements:
- Keep it under 200 characters
- Be warm and friendly
- Include an emoji or two
- Just write the message, nothing else"""

        response = await self.http_client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.8  # Higher = more creative/varied
            }
        )
        
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    
    async def cleanup(self):
        """Close the HTTP client when done."""
        await self.http_client.aclose()


class GeminiMessageEvaluator(MessageEvaluator):
    """
    Uses Google's Gemini to evaluate message quality.
    
    Why Gemini instead of GPT? Because using GPT to evaluate GPT feels like 
    letting students grade their own homework. An independent reviewer gives 
    more honest feedback.
    """
    
    # What we ask Gemini to evaluate
    EVALUATION_PROMPT = """
You're reviewing a healthcare appointment reminder. Be honest and critical.

Score each criterion from 1 to 5:
1. COMPLETENESS - Does it include date, time, doctor name, and location?
2. TONE - Does it sound friendly and warm, or cold and robotic?
3. CLARITY - Would anyone (including elderly patients) understand it easily?
4. LENGTH - Is it appropriate for a text message (not too long, not too short)?
5. PROFESSIONALISM - Is it appropriate for a medical context?

Don't be too generous - a 5 should be genuinely excellent.
"""
    
    def __init__(self, api_key: str, minimum_passing_score: float = 4.0):
        self.api_key = api_key
        self.minimum_passing_score = minimum_passing_score
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def evaluate_message(self, message: str, appointment: Appointment) -> EvaluationResult:
        prompt = f"""{self.EVALUATION_PROMPT}

Appointment details:
- Patient: {appointment.patient_name}
- Type: {appointment.appointment_type}
- Time: {appointment.get_formatted_time()}
- Doctor: {appointment.doctor_name}
- Location: {appointment.clinic_location}

Message to evaluate:
"{message}"

Respond with ONLY this JSON (no markdown, no extra text):
{{"completeness": <1-5>, "tone": <1-5>, "clarity": <1-5>, "length": <1-5>, "professionalism": <1-5>, "feedback": "<brief explanation>"}}"""

        response = await self.http_client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200}
            }
        )
        
        return self._parse_gemini_response(response.json())
    
    def _parse_gemini_response(self, response_data: dict) -> EvaluationResult:
        """Convert Gemini's response into our EvaluationResult structure."""
        try:
            text = response_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            # Gemini sometimes wraps JSON in markdown code blocks
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            
            data = json.loads(text)
            
            scores = QualityScores(
                completeness=data["completeness"],
                tone=data["tone"],
                clarity=data["clarity"],
                length=data["length"],
                professionalism=data["professionalism"],
                feedback=data.get("feedback", "")
            )
            
            average = scores.get_average()
            
            return EvaluationResult(
                scores=scores,
                average_score=average,
                passed_quality_check=average >= self.minimum_passing_score
            )
            
        except Exception as error:
            # If we can't parse the response, don't block the message
            # Better to send a potentially imperfect message than no message
            print(f"    Warning: Couldn't parse Gemini's response ({error})")
            
            empty_scores = QualityScores(0, 0, 0, 0, 0, f"Parse error: {error}")
            return EvaluationResult(
                scores=empty_scores,
                average_score=0,
                passed_quality_check=True  # Default to passing on error
            )
    
    async def cleanup(self):
        """Close the HTTP client when done."""
        await self.http_client.aclose()


class TwilioWhatsAppSender(MessageSender):
    """
    Sends messages via Twilio's WhatsApp API.
    
    Note: For testing, you need to join Twilio's WhatsApp sandbox first.
    See: https://www.twilio.com/docs/whatsapp/sandbox
    """
    
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.client = TwilioClient(account_sid, auth_token)
        self.from_number = from_number
    
    def send_message(self, message: str, recipient: str) -> bool:
        try:
            result = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=recipient
            )
            print(f"    📱 Sent! Message ID: {result.sid[:20]}...")
            return True
            
        except Exception as error:
            print(f"    ❌ Failed to send: {error}")
            return False


# ============================================================================
# THE PIPELINE
# Orchestrates everything: write → evaluate → decide → send
# ============================================================================

class ReminderPipeline:
    """
    The main orchestrator. Takes an appointment and:
    1. Asks GPT to write a message
    2. Asks Gemini to evaluate it
    3. Decides whether to use the AI message or a safe fallback
    4. Sends the final message via WhatsApp
    
    You can swap out any component (writer, evaluator, sender) without 
    changing this code - just pass in a different implementation.
    """
    
    # If AI message fails quality check, we send this instead
    # Boring? Yes. But patients always get their reminder.
    SAFE_FALLBACK_TEMPLATE = (
        "Hi {name}, this is a reminder about your {type} appointment "
        "with {doctor} on {time} at {location}."
    )
    
    def __init__(
        self,
        writer: MessageWriter,
        evaluator: MessageEvaluator,
        sender: MessageSender,
        patient_phone: str
    ):
        self.writer = writer
        self.evaluator = evaluator
        self.sender = sender
        self.patient_phone = patient_phone
    
    async def send_reminder(self, appointment: Appointment) -> ReminderResult:
        """Run the full pipeline for an appointment."""
        
        self._print_header()
        
        # Step 1: GPT writes a message
        print("\n[Step 1] GPT is writing a personalized message...")
        ai_message = await self.writer.write_message(appointment)
        print(f'\n    "{ai_message}"')
        
        # Step 2: Gemini evaluates it
        print("\n[Step 2] Gemini is evaluating the message...")
        evaluation = await self.evaluator.evaluate_message(ai_message, appointment)
        self._print_evaluation(evaluation)
        
        # Step 3: Decide what to send
        print(f"\n[Step 3] Quality check (minimum score: {self.evaluator.minimum_passing_score})...")
        final_message, status = self._decide_what_to_send(ai_message, evaluation, appointment)
        
        # Step 4: Send it
        print("\n[Step 4] Sending via WhatsApp...")
        send_successful = self.sender.send_message(final_message, self.patient_phone)
        
        if not send_successful:
            status = "failed"
        
        self._print_footer(status)
        
        return ReminderResult(
            message_sent=final_message,
            evaluation=evaluation,
            status=status
        )
    
    def _decide_what_to_send(
        self, 
        ai_message: str, 
        evaluation: EvaluationResult,
        appointment: Appointment
    ) -> tuple:
        """Choose between AI message and safe fallback based on quality score."""
        
        if evaluation.passed_quality_check:
            print(f"    ✓ Score {evaluation.average_score}/5 - Passed! Using AI message.")
            return ai_message, "sent_ai"
        else:
            print(f"    ✗ Score {evaluation.average_score}/5 - Too low. Using safe fallback.")
            
            fallback = self.SAFE_FALLBACK_TEMPLATE.format(
                name=appointment.patient_name,
                type=appointment.appointment_type,
                doctor=appointment.doctor_name,
                time=appointment.get_formatted_time(),
                location=appointment.clinic_location
            )
            print(f'    Fallback: "{fallback}"')
            
            return fallback, "sent_fallback"
    
    def _print_header(self):
        print("\n" + "=" * 60)
        print("  HEALTHCARE AI REMINDER PIPELINE")
        print("=" * 60)
    
    def _print_footer(self, status: str):
        status_emoji = {"sent_ai": "✅", "sent_fallback": "⚠️", "failed": "❌"}
        print(f"\n{'=' * 60}")
        print(f"  {status_emoji.get(status, '?')} Complete! Status: {status}")
        print("=" * 60)
    
    def _print_evaluation(self, evaluation: EvaluationResult):
        s = evaluation.scores
        print(f"""
    Scores from Gemini:
    ├─ Completeness:    {s.completeness}/5
    ├─ Tone:            {s.tone}/5
    ├─ Clarity:         {s.clarity}/5
    ├─ Length:          {s.length}/5
    └─ Professionalism: {s.professionalism}/5
    
    Average: {evaluation.average_score}/5
    Feedback: {s.feedback}""")


# ============================================================================
# FACTORY
# Creates a fully configured pipeline with one line of code
# ============================================================================

def create_reminder_system(settings: Settings = None) -> ReminderPipeline:
    """
    Factory function to create a configured reminder pipeline.
    
    Usage:
        pipeline = create_reminder_system()
        await pipeline.send_reminder(appointment)
    """
    settings = settings or Settings()
    
    writer = GPTMessageWriter(api_key=settings.openai_key)
    evaluator = GeminiMessageEvaluator(
        api_key=settings.gemini_key,
        minimum_passing_score=settings.minimum_quality_score
    )
    sender = TwilioWhatsAppSender(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_whatsapp_number
    )
    
    return ReminderPipeline(
        writer=writer,
        evaluator=evaluator,
        sender=sender,
        patient_phone=settings.patient_phone
    )


# ============================================================================
# WRAPPER FOR app.py
# Keeps the simple interface that app.py expects
# ============================================================================

class ReminderSystem:
    """
    Simple wrapper that app.py uses.
    Provides an easy-to-use interface for the reminder pipeline.
    """
    
    def __init__(self):
        self.settings = Settings()
        self.pipeline = create_reminder_system(self.settings)
    
    async def send_reminder(
        self, 
        appt_type: str, 
        appt_time: datetime, 
        doctor: str, 
        location: str
    ) -> dict:
        """Send a reminder and return the result as a dictionary."""
        
        appointment = Appointment(
            patient_name=self.settings.patient_name,
            appointment_type=appt_type,
            doctor_name=doctor,
            clinic_location=location,
            appointment_time=appt_time
        )
        
        result = await self.pipeline.send_reminder(appointment)
        
        # Convert to the dict format that app.py expects
        return {
            "message": result.message_sent,
            "evaluation": {
                "scores": result.evaluation.scores.to_dict(),
                "avg": result.evaluation.average_score,
                "feedback": result.evaluation.scores.feedback,
                "passed": result.evaluation.passed_quality_check
            },
            "status": result.status
        }
    
    async def close(self):
        """Clean up HTTP clients."""
        await self.pipeline.writer.cleanup()
        await self.pipeline.evaluator.cleanup()


# ============================================================================
# TEST IT OUT
# Run this file directly to see the pipeline in action
# ============================================================================

async def main():
    """Demo the system with a test appointment."""
    
    print("\n" + "~" * 60)
    print("  Healthcare AI Reminder System")
    print("  GPT writes → Gemini evaluates → Twilio sends")
    print("~" * 60)
    
    # Load environment variables from .env file
    from dotenv import load_dotenv
    load_dotenv()
    
    # Create and validate settings
    settings = Settings()
    if not settings.validate():
        return
    
    pipeline = create_reminder_system(settings)
    
    # Create a test appointment for tomorrow
    tomorrow_10am = datetime.now() + timedelta(days=1)
    tomorrow_10am = tomorrow_10am.replace(hour=10, minute=0, second=0)
    
    appointment = Appointment(
        patient_name=settings.patient_name,
        appointment_type="Annual Health Checkup",
        doctor_name="Dr. Sarah Wilson",
        clinic_location="City Health Clinic",
        appointment_time=tomorrow_10am
    )
    
    # Run the pipeline
    await pipeline.send_reminder(appointment)
    
    print("\n📱 Check your WhatsApp!")
    
    # Cleanup
    await pipeline.writer.cleanup()
    await pipeline.evaluator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
