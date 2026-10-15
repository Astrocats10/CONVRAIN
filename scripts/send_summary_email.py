"""
ส่งสรุปรายงานผลลัพธ์ CONVRAIN ไปยังอีเมลปลายทางผ่าน Gmail SMTP
การใช้งาน:
    python scripts/send_summary_email.py --to kannop10@gmail.com
"""
from __future__ import annotations

import argparse
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path.home() / ".env")

def send_email(to_email: str, subject: str, html_body: str, text_body: str = None) -> bool:
    smtp_user = os.getenv("GMAIL_USER") or os.getenv("SMTP_USER") or os.getenv("USER_EMAIL")
    smtp_pass = os.getenv("GMAIL_APP_PASS") or os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not smtp_user or not smtp_pass:
        print("[ERROR] ไม่พบบัญชีผู้ส่งหรือรหัสผ่าน SMTP ใน .env")
        print("กรุณาระบุ GMAIL_USER และ GMAIL_APP_PASS (App Password 16 หลัก) ใน .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"CONVRAIN Validation System <{smtp_user}>"
    msg["To"] = to_email

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        print(f"กำลังเชื่อมต่อไปยัง {smtp_server}:{smtp_port}...")
        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
        print(f"[SUCCESS] ส่งอีเมลไปยัง {to_email} เรียบร้อยแล้ว!")
        return True
    except Exception as e:
        print(f"[FAILED] ส่งอีเมลไม่สำเร็จ: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Send CONVRAIN summary report email")
    parser.add_argument("--to", default="kannop10@gmail.com", help="Recipient email address")
    parser.add_argument("--html", default="d:/งานพี/convrain/reports/convrain_summary_email.html", help="Path to HTML report")
    args = parser.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        raise SystemExit(f"ไม่พบไฟล์ HTML ที่ {html_path}")

    html_content = html_path.read_text(encoding="utf-8")
    subject = "🛰️ สรุปผลการประเมินระบบเตือนภัย CONVRAIN (Lead Time, POD, FOR) เทียบเรดาร์ TMD"
    
    send_email(args.to, subject, html_content)

if __name__ == "__main__":
    main()
