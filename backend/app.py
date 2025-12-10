"""
Healthcare AI Evaluation Pipeline - Dashboard & Auto-Scheduler

This is the main entry point. It does two things:
1. Runs an auto-scheduler that sends reminders every 10 minutes
2. Serves a dashboard showing real-time analytics

The dashboard shows:
- How many messages were sent
- What scores Gemini gave each message
- Whether we used the AI message or fallback
- Gemini's feedback on each message

Run:  python app.py
Open: http://localhost:8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import asyncio
import json
import os

from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

from simple_reminder import ReminderSystem


# ============================================================================
# CONFIGURATION
# ============================================================================

# How often to send reminders (in seconds)
# 600 = 10 minutes. Change to 60 for faster demo.
REMINDER_INTERVAL_SECONDS = 600

# Where we save the dashboard data (so it survives restarts)
DATA_FILE = "dashboard_data.json"

# The appointment we're sending reminders about
# In a real system, this would come from a database
APPOINTMENT_DETAILS = {
    "type": "Annual Health Checkup",
    "doctor": "Dr. Sarah Wilson",
    "location": "City Health Clinic"
}


# ============================================================================
# PERSISTENCE (Save/Load Dashboard Data)
# ============================================================================

def load_saved_data() -> dict:
    """
    Load dashboard data from file. 
    This means your stats survive server restarts.
    """
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as file:
                return json.load(file)
        except Exception:
            pass  # If file is corrupted, start fresh
    
    # Default empty data structure
    return {"messages": [], "daily": {}}


def save_data_to_file():
    """Save current dashboard data to file."""
    try:
        with open(DATA_FILE, "w") as file:
            json.dump(dashboard_data, file, indent=2)
    except Exception as error:
        print(f"Warning: Couldn't save data: {error}")


# Initialize the reminder system and load saved data
reminder_system = ReminderSystem()
dashboard_data = load_saved_data()
scheduler_task = None


# ============================================================================
# AUTO-SCHEDULER
# Runs in the background, sending reminders automatically
# ============================================================================

async def auto_send_reminders():
    """
    Background task that sends a reminder every REMINDER_INTERVAL_SECONDS.
    
    This simulates a real healthcare system that sends multiple reminders
    for the same appointment (e.g., 7 days before, 1 day before, etc.)
    """
    # Give the dashboard time to load first
    print(f"⏳ First reminder in 30 seconds...")
    await asyncio.sleep(30)
    
    while True:
        try:
            # Calculate "tomorrow at 10 AM" for the appointment time
            appointment_time = datetime.now() + timedelta(days=1)
            appointment_time = appointment_time.replace(hour=10, minute=0, second=0)
            
            print(f"\n🔔 Sending automated reminder...")
            
            # Run the AI pipeline (GPT writes → Gemini evaluates → Twilio sends)
            result = await reminder_system.send_reminder(
                appt_type=APPOINTMENT_DETAILS["type"],
                appt_time=appointment_time,
                doctor=APPOINTMENT_DETAILS["doctor"],
                location=APPOINTMENT_DETAILS["location"]
            )
            
            # Update dashboard statistics
            record_message_in_dashboard(result, APPOINTMENT_DETAILS)
            
        except Exception as error:
            print(f"❌ Error in auto-scheduler: {error}")
        
        # Wait before sending the next reminder
        minutes = REMINDER_INTERVAL_SECONDS // 60
        print(f"\n⏳ Next reminder in {minutes} minutes...")
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)


def record_message_in_dashboard(result: dict, appointment: dict):
    """
    Record a sent message in the dashboard data.
    This updates the stats and saves to file.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Initialize today's stats if needed
    if today not in dashboard_data["daily"]:
        dashboard_data["daily"][today] = {
            "sent": 0,
            "fallback": 0, 
            "failed": 0,
            "total_score": 0,
            "count": 0
        }
    
    # Update daily statistics
    daily_stats = dashboard_data["daily"][today]
    daily_stats["count"] += 1
    daily_stats["total_score"] += result["evaluation"]["avg"]
    
    if result["status"] == "sent_ai":
        daily_stats["sent"] += 1
    elif result["status"] == "sent_fallback":
        daily_stats["fallback"] += 1
    else:
        daily_stats["failed"] += 1
    
    # Add to message history
    message_text = result["message"]
    if len(message_text) > 100:
        message_text = message_text[:100] + "..."
    
    dashboard_data["messages"].append({
        "time": datetime.now().isoformat(),
        "type": appointment["type"],
        "doctor": appointment["doctor"],
        "score": result["evaluation"]["avg"],
        "scores": result["evaluation"].get("scores", {}),
        "feedback": result["evaluation"].get("feedback", ""),
        "status": result["status"],
        "message": message_text
    })
    
    # Keep only the last 50 messages
    if len(dashboard_data["messages"]) > 50:
        dashboard_data["messages"] = dashboard_data["messages"][-50:]
    
    # Save to file
    save_data_to_file()
                


@asynccontextmanager
async def lifespan(app):
    """
    Startup and shutdown logic for the FastAPI app.
    Starts the auto-scheduler when server starts, cleans up when it stops.
    """
    global scheduler_task
    
    # Startup
    minutes = REMINDER_INTERVAL_SECONDS // 60
    print(f"\n🚀 Healthcare AI Pipeline Started!")
    print(f"   Auto-reminders: every {minutes} minutes")
    print(f"   Dashboard: http://localhost:8000")
    
    scheduler_task = asyncio.create_task(auto_send_reminders())
    
    yield  # Server runs here
    
    # Shutdown
    if scheduler_task:
        scheduler_task.cancel()
    await reminder_system.close()


app = FastAPI(title="Healthcare AI Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/analytics")
async def get_analytics():
    """
    API endpoint that returns dashboard data.
    The frontend polls this every 5 seconds to update the display.
    """
    messages = dashboard_data["messages"]
    
    # Calculate summary statistics
    total_messages = len(messages)
    ai_approved = sum(1 for m in messages if m["status"] == "sent_ai")
    used_fallback = sum(1 for m in messages if m["status"] == "sent_fallback")
    failed = sum(1 for m in messages if m["status"] == "failed")
    
    average_score = 0
    if total_messages > 0:
        average_score = sum(m["score"] for m in messages) / total_messages
    
    # Calculate pass rate (% of messages that used AI vs fallback)
    pass_rate = 0
    if total_messages > 0:
        pass_rate = (ai_approved / total_messages) * 100
    
    # Build chart data for the last 7 days
    chart_data = []
    for days_ago in range(6, -1, -1):
        date = datetime.now() - timedelta(days=days_ago)
        date_key = date.strftime("%Y-%m-%d")
        day_label = date.strftime("%a")  # Mon, Tue, etc.
        
        if date_key in dashboard_data["daily"]:
            day_stats = dashboard_data["daily"][date_key]
            day_avg = 0
            if day_stats["count"] > 0:
                day_avg = round(day_stats["total_score"] / day_stats["count"], 1)
            
            chart_data.append({
                "day": day_label,
                "sent": day_stats["sent"],
                "fallback": day_stats["fallback"],
                "failed": day_stats["failed"],
                "avg_score": day_avg
            })
        else:
            chart_data.append({
                "day": day_label,
                "sent": 0,
                "fallback": 0,
                "failed": 0,
                "avg_score": 0
            })
    
    return {
        "summary": {
            "total": total_messages,
            "sent_ai": ai_approved,
            "sent_fallback": used_fallback,
            "failed": failed,
            "avg_score": round(average_score, 2),
            "pass_rate": round(pass_rate, 1)
        },
        "chart": chart_data,
        "recent": messages[-10:][::-1]  # Last 10, newest first
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Healthcare AI Evaluation Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --bg: #0f0f14;
            --card: #1a1a23;
            --border: #2a2a35;
            --text: #e4e4e7;
            --muted: #71717a;
            --green: #22c55e;
            --yellow: #eab308;
            --red: #ef4444;
            --blue: #3b82f6;
            --purple: #a855f7;
        }

        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 2rem;
        }

        .container { max-width: 1400px; margin: 0 auto; }

        header {
            margin-bottom: 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        h1 { font-size: 1.75rem; font-weight: 700; }
        .subtitle { color: var(--muted); font-size: 0.9rem; margin-top: 0.25rem; }

        .live {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid var(--green);
            border-radius: 100px;
            font-size: 0.85rem;
            color: var(--green);
        }

        .dot {
            width: 8px;
            height: 8px;
            background: var(--green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        .pipeline {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 1.5rem;
            background: linear-gradient(135deg, var(--card) 0%, #1f1f2e 100%);
            border: 1px solid var(--border);
            border-radius: 12px;
            margin-bottom: 2rem;
        }

        .node {
            text-align: center;
            padding: 1rem;
        }

        .icon {
            width: 50px;
            height: 50px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            margin: 0 auto 0.5rem;
        }

        .icon.schedule { background: rgba(234, 88, 12, 0.2); }
        .icon.writer { background: rgba(59, 130, 246, 0.2); }
        .icon.judge { background: rgba(168, 85, 247, 0.2); }
        .icon.send { background: rgba(34, 197, 94, 0.2); }

        .label { font-size: 0.75rem; color: var(--muted); }
        .arrow { font-size: 1.5rem; color: var(--border); }

        .stats {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 1rem;
            margin-bottom: 2rem;
        }

        @media (max-width: 1000px) {
            .stats { grid-template-columns: repeat(3, 1fr); }
        }

        .stat {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.25rem;
        }

        .stat-label {
            font-size: 0.75rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }

        .stat-value { font-size: 2rem; font-weight: 700; }
        .stat-value.green { color: var(--green); }
        .stat-value.yellow { color: var(--yellow); }
        .stat-value.blue { color: var(--blue); }

        .grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
        }

        @media (max-width: 900px) {
            .grid { grid-template-columns: 1fr; }
        }

        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
        }

        .card-title {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 1rem;
        }

        .chart-box { height: 300px; }

        .feed { max-height: 400px; overflow-y: auto; }

        .item {
            padding: 1rem;
            background: var(--bg);
            border-radius: 8px;
            margin-bottom: 0.75rem;
            border-left: 3px solid var(--border);
        }

        .item.sent_ai { border-left-color: var(--green); }
        .item.sent_fallback { border-left-color: var(--yellow); }
        .item.failed { border-left-color: var(--red); }

        .item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }

        .item-type { font-weight: 600; font-size: 0.9rem; }

        .score {
            font-weight: 600;
            font-size: 0.85rem;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            background: var(--card);
        }

        .score.high { color: var(--green); }
        .score.mid { color: var(--yellow); }
        .score.low { color: var(--red); }

        .item-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .time { font-size: 0.75rem; color: var(--muted); }

        .badge {
            font-size: 0.7rem;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
        }

        .badge.sent_ai { background: rgba(34, 197, 94, 0.2); color: var(--green); }
        .badge.sent_fallback { background: rgba(234, 179, 8, 0.2); color: var(--yellow); }
        .badge.failed { background: rgba(239, 68, 68, 0.2); color: var(--red); }

        .msg {
            font-size: 0.85rem;
            color: var(--muted);
            margin-top: 0.5rem;
            font-style: italic;
        }

        .eval-scores {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-top: 0.5rem;
        }

        .eval-chip {
            font-size: 0.7rem;
            padding: 0.2rem 0.4rem;
            background: var(--bg);
            border-radius: 4px;
            color: var(--muted);
        }

        .feedback {
            font-size: 0.75rem;
            color: var(--purple);
            margin-top: 0.5rem;
            padding: 0.5rem;
            background: rgba(168, 85, 247, 0.1);
            border-radius: 4px;
            border-left: 2px solid var(--purple);
        }

        .empty {
            text-align: center;
            padding: 3rem;
            color: var(--muted);
        }

        .empty-icon { font-size: 3rem; margin-bottom: 1rem; }
        
        .footer {
            text-align: center;
            color: var(--muted);
            font-size: 0.8rem;
            margin-top: 1.5rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>🏥 Healthcare AI Evaluation Dashboard</h1>
                <p class="subtitle">Cross-model AI evaluation: GPT writes, Gemini judges</p>
            </div>
            <div class="live">
                <div class="dot"></div>
                fully automated
            </div>
        </header>

        <div class="pipeline">
            <div class="node">
                <div class="icon schedule">⏰</div>
                <div class="label">Auto Schedule</div>
            </div>
            <div class="arrow">→</div>
            <div class="node">
                <div class="icon writer">✍️</div>
                <div class="label">GPT Writes</div>
            </div>
            <div class="arrow">→</div>
            <div class="node">
                <div class="icon judge">⚖️</div>
                <div class="label">Gemini Judges</div>
            </div>
            <div class="arrow">→</div>
            <div class="node">
                <div class="icon send">📱</div>
                <div class="label">WhatsApp</div>
            </div>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-label">Total Sent</div>
                <div class="stat-value" id="total">0</div>
            </div>
            <div class="stat">
                <div class="stat-label">AI Approved</div>
                <div class="stat-value green" id="ai">0</div>
            </div>
            <div class="stat">
                <div class="stat-label">Used Fallback</div>
                <div class="stat-value yellow" id="fallback">0</div>
            </div>
            <div class="stat">
                <div class="stat-label">Avg Score</div>
                <div class="stat-value blue" id="score">0</div>
            </div>
            <div class="stat">
                <div class="stat-label">Pass Rate</div>
                <div class="stat-value green" id="rate">0%</div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-title">📊 Evaluation Scores This Week</div>
                <div class="chart-box">
                    <canvas id="chart"></canvas>
                </div>
            </div>

            <div class="card">
                <div class="card-title">📜 Recent Messages</div>
                <div class="feed" id="feed">
                    <div class="empty">
                        <div class="empty-icon">⏳</div>
                        <p>Waiting for first message...</p>
                        <p style="font-size: 0.8rem; margin-top: 0.5rem;">Coming in ~30 seconds</p>
                    </div>
                </div>
            </div>
        </div>
        
        <p class="footer">
            GPT-4o-mini writes personalized reminders • Gemini-2.0-Flash evaluates quality • Twilio delivers via WhatsApp<br>
            <span style="color: var(--purple);">Cross-model evaluation ensures unbiased quality control</span>
        </p>
    </div>

    <script>
        let chart = null;

        function formatTime(iso) {
            return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
        }

        function scoreClass(s) {
            if (s >= 4) return 'high';
            if (s >= 3) return 'mid';
            return 'low';
        }

        function statusLabel(s) {
            if (s === 'sent_ai') return '✅ AI Approved';
            if (s === 'sent_fallback') return '⚠️ Fallback';
            return '❌ Failed';
        }

        function update(d) {
            document.getElementById('total').textContent = d.summary.total;
            document.getElementById('ai').textContent = d.summary.sent_ai;
            document.getElementById('fallback').textContent = d.summary.sent_fallback;
            document.getElementById('score').textContent = d.summary.avg_score + '/5';
            document.getElementById('rate').textContent = d.summary.pass_rate + '%';

            const labels = d.chart.map(x => x.day);
            const scores = d.chart.map(x => x.avg_score);
            const sent = d.chart.map(x => x.sent + x.fallback);

            if (chart) {
                chart.data.labels = labels;
                chart.data.datasets[0].data = scores;
                chart.data.datasets[1].data = sent;
                chart.update();
            } else {
                chart = new Chart(document.getElementById('chart'), {
                    type: 'bar',
                    data: {
                        labels,
                        datasets: [
                            {
                                label: 'Avg Score',
                                data: scores,
                                backgroundColor: 'rgba(59, 130, 246, 0.8)',
                                borderRadius: 4,
                                yAxisID: 'y'
                            },
                            {
                                label: 'Messages',
                                data: sent,
                                type: 'line',
                                borderColor: '#22c55e',
                                backgroundColor: 'rgba(34, 197, 94, 0.1)',
                                fill: true,
                                tension: 0.4,
                                yAxisID: 'y1'
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { labels: { color: '#71717a' } } },
                        scales: {
                            x: { grid: { color: '#2a2a35' }, ticks: { color: '#71717a' } },
                            y: { position: 'left', min: 0, max: 5, grid: { color: '#2a2a35' }, ticks: { color: '#71717a' } },
                            y1: { position: 'right', min: 0, grid: { display: false }, ticks: { color: '#71717a' } }
                        }
                    }
                });
            }

            const feed = document.getElementById('feed');
            if (d.recent.length === 0) {
                feed.innerHTML = `<div class="empty"><div class="empty-icon">⏳</div><p>Waiting for first message...</p><p style="font-size: 0.8rem; margin-top: 0.5rem;">Coming in ~30 seconds</p></div>`;
            } else {
                feed.innerHTML = d.recent.map(m => `
                    <div class="item ${m.status}">
                        <div class="item-header">
                            <span class="item-type">${m.type}</span>
                            <span class="score ${scoreClass(m.score)}">${m.score}/5</span>
                        </div>
                        <div class="item-meta">
                            <span class="time">${formatTime(m.time)} • ${m.doctor}</span>
                            <span class="badge ${m.status}">${statusLabel(m.status)}</span>
                        </div>
                        <div class="msg">"${m.message}"</div>
                        ${m.scores ? `
                        <div class="eval-scores">
                            <span class="eval-chip">Complete: ${m.scores.completeness || '?'}</span>
                            <span class="eval-chip">Tone: ${m.scores.tone || '?'}</span>
                            <span class="eval-chip">Clarity: ${m.scores.clarity || '?'}</span>
                            <span class="eval-chip">Length: ${m.scores.length || '?'}</span>
                            <span class="eval-chip">Professional: ${m.scores.professionalism || '?'}</span>
                        </div>
                        ` : ''}
                        ${m.feedback ? `<div class="feedback"><strong>Gemini:</strong> ${m.feedback}</div>` : ''}
                    </div>
                `).join('');
            }
        }

        async function load() {
            try {
                const res = await fetch('/api/analytics');
                update(await res.json());
            } catch (e) {
                console.error('fetch failed:', e);
            }
        }

        load();
        setInterval(load, 5000);
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
