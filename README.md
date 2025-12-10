# Healthcare AI Reminder System with Cross-Model Evaluation

An automated healthcare reminder system that uses **cross-model AI evaluation** - GPT writes personalized messages, Gemini judges their quality.

## Why This Matters

Most reminder systems send the same boring template to everyone. This one uses AI to personalize messages - but here's the key insight: **I don't trust GPT to judge its own work**. That's like letting students grade their own tests.

So I use **Gemini as an independent reviewer**. If the message passes quality checks (score 4+/5), it gets sent. If not, we fall back to a safe template. Either way, the patient gets reminded.

## The Pipeline

```
┌─────────────────────────────────────────────────────────┐
│                    AUTO SCHEDULER                       │
│                  (every 10 minutes)                     │
└─────────────────────┬───────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│                   GPT-4o-mini                           │
│            Writes personalized message                  │
│   "Hey Sangeeth! 😊 Reminder about your checkup..."    │
└─────────────────────┬───────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│                 GEMINI-2.0-FLASH                        │
│              Evaluates the message                      │
│                                                         │
│   Completeness:    5/5                                  │
│   Tone:            4/5                                  │
│   Clarity:         5/5                                  │
│   Length:          5/5                                  │
│   Professionalism: 4/5                                  │
│   ─────────────────────                                 │
│   Average:         4.6/5  ✓ PASSED                      │
└─────────────────────┬───────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│                  QUALITY GATE                           │
│                                                         │
│   Score >= 4.0  →  Send AI message                      │
│   Score < 4.0   →  Send safe fallback template          │
└─────────────────────┬───────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│                TWILIO WHATSAPP                          │
│              Message delivered! 📱                      │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Clone and install dependencies
```bash
git clone https://github.com/sangeeths29/healthcare_reminder_system.git
cd healthcare_reminder_system
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set up environment variables
```bash
cp .env.example .env
```

Edit `.env` and add your API keys:
- **OpenAI API Key**: Get from [OpenAI Platform](https://platform.openai.com/api-keys)
- **Gemini API Key**: Get from [Google AI Studio](https://aistudio.google.com/apikey)
- **Twilio Credentials**: Get from [Twilio Console](https://console.twilio.com)

### 3. Join Twilio WhatsApp Sandbox
1. Go to [Twilio Console](https://console.twilio.com)
2. Navigate to Messaging → Try it out → Send a WhatsApp message
3. Send the join code to the Twilio sandbox number from your phone

### 4. Run
```bash
cd backend
python app.py
```

### 5. Open dashboard
http://localhost:8000

First message sends in 30 seconds, then every 10 minutes automatically.

## What You'll See

**Dashboard shows:**
- Pipeline visualization
- Total messages sent
- AI approval rate
- Average evaluation scores
- Recent messages with individual scores
- Gemini's feedback for each message

**Terminal shows:**
```
[1] GPT is writing the message...
    "Hey Sangeeth! 😊 Just a reminder..."

[2] Gemini is reviewing it...
    Completeness: 5/5
    Tone: 4/5
    Clarity: 5/5
    Length: 5/5
    Professionalism: 4/5
    Average: 4.6/5

[3] Quality gate (need 4.0+ to pass)...
    ✓ Passed! Sending AI message...

[4] Sending WhatsApp...
    📱 WhatsApp sent!
```

## Project Structure

```
healthcare_reminder_system/
├── backend/
│   ├── app.py              # Dashboard + auto-scheduler
│   └── simple_reminder.py  # AI pipeline (SOLID architecture)
├── .env.example            # Template for environment variables
├── .gitignore
├── requirements.txt
└── README.md
```

## Code Architecture (SOLID Principles)

The code follows **SOLID design principles** for clean, maintainable architecture:

### S - Single Responsibility
Each class has one job:
- `GPTMessageWriter` - Only generates messages
- `GeminiMessageEvaluator` - Only evaluates messages  
- `TwilioWhatsAppSender` - Only sends messages
- `ReminderPipeline` - Only orchestrates the flow

### O - Open/Closed
Easy to extend without modifying existing code:
```python
# Want to use Claude instead of GPT? Just create:
class ClaudeMessageWriter(MessageWriter):
    async def write(self, appointment): ...
```

### L - Liskov Substitution
All implementations are interchangeable:
```python
# Any MessageWriter works in the pipeline
pipeline = ReminderPipeline(
    writer=GPTMessageWriter(...),      # or ClaudeMessageWriter
    evaluator=GeminiMessageEvaluator(...),
    sender=TwilioWhatsAppSender(...)   # or EmailSender
)
```

### I - Interface Segregation
Small, focused interfaces:
```python
class MessageWriter(ABC):
    async def write(self, appointment) -> str: ...

class MessageEvaluator(ABC):
    async def evaluate(self, message, appointment) -> EvaluationResult: ...

class MessageSender(ABC):
    def send(self, message, recipient) -> bool: ...
```

### D - Dependency Inversion
High-level modules depend on abstractions:
```python
class ReminderPipeline:
    def __init__(
        self,
        writer: MessageWriter,      # Interface, not GPTMessageWriter
        evaluator: MessageEvaluator, # Interface, not GeminiEvaluator
        sender: MessageSender        # Interface, not TwilioSender
    ): ...
```

## Key Concepts

### Cross-Model Evaluation
Using the same model to evaluate itself creates bias. By using GPT for generation and Gemini for evaluation, we get an independent quality check.

### Quality Gate with Fallback
AI isn't perfect. If evaluation fails, we don't skip the reminder - we send a safe template instead. Patient safety comes first.

### Evaluation Criteria
Vague questions get vague answers. Instead of "is this good?", we score:
- **Completeness** - Has date, time, doctor, location?
- **Tone** - Friendly or robotic?
- **Clarity** - Would anyone understand this?
- **Length** - Appropriate for a text message?
- **Professionalism** - Suitable for healthcare?

## Tech Stack

| Component | Technology |
|-----------|------------|
| Message Generation | GPT-4o-mini |
| Message Evaluation | Gemini-2.0-Flash |
| Message Delivery | Twilio WhatsApp |
| Dashboard | FastAPI + Chart.js |
| Scheduling | Python asyncio |

---

## Disclaimer

This is a portfolio project for learning purposes. Not intended for production healthcare use.

## License

MIT License - see [LICENSE](LICENSE) for details.
