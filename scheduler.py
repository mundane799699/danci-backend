from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from database import SessionLocal
from models import UserSubscribeMail
from email_service import EmailService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self, test_mode=False):
        self.scheduler = BackgroundScheduler()
        self.email_service = EmailService()
        self.job_ids = set()
        self.test_mode = test_mode

    def start(self):
        self.scheduler.start()
        logger.info("定时任务调度器已启动")

    def stop(self):
        self.scheduler.shutdown()
        logger.info("定时任务调度器已停止")

    def schedule_user_email(self, user_subscribe: UserSubscribeMail):
        """为单个用户调度邮件发送任务"""
        try:
            if self.test_mode:
                # 测试模式：每20秒触发一次
                trigger = IntervalTrigger(seconds=20)
                logger.info("使用测试模式：每20秒触发一次")
            else:
                # 正常模式：使用用户设置的时间
                hour, minute = map(int, user_subscribe.send_time.split(':'))
                trigger = CronTrigger(hour=hour, minute=minute)
            
            # 创建定时任务
            job_id = f"email_{user_subscribe.id}"
            self.scheduler.add_job(
                self._send_email_job,
                trigger,
                args=[user_subscribe.id],
                id=job_id,
                replace_existing=True
            )
            self.job_ids.add(job_id)
            logger.info(f"已为用户订阅ID {user_subscribe.id} 设置定时邮件任务，发送时间: {user_subscribe.send_time if not self.test_mode else '每20秒'}")
        except Exception as e:
            logger.error(f"设置定时任务失败: {str(e)}")

    def _send_email_job(self, subscribe_id: int):
        """执行邮件发送任务"""
        db = SessionLocal()
        try:
            user_subscribe = db.query(UserSubscribeMail).filter(UserSubscribeMail.id == subscribe_id).first()
            if user_subscribe:
                # 根据邮件类型发送不同的邮件
                if user_subscribe.mail_type == "quote":
                    # 发送金句邮件
                    self.email_service.send_quote_email(db, user_subscribe)
                    logger.info(f"已发送金句邮件给用户订阅ID {user_subscribe.id}")
                else:
                    # 发送单词邮件（默认）
                    self.email_service.send_word_email(db, user_subscribe)
                    logger.info(f"已发送单词邮件给用户订阅ID {user_subscribe.id}")
        except Exception as e:
            logger.error(f"发送邮件失败: {str(e)}")
        finally:
            db.close()

    def schedule_all_users(self):
        """为所有订阅用户调度邮件任务"""
        db = SessionLocal()
        try:
            subscriptions = db.query(UserSubscribeMail).all()
            for subscription in subscriptions:
                self.schedule_user_email(subscription)
        finally:
            db.close()

    def remove_job(self, subscribe_id: int):
        """移除用户的定时任务"""
        job_id = f"email_{subscribe_id}"
        if job_id in self.job_ids:
            self.scheduler.remove_job(job_id)
            self.job_ids.remove(job_id)
            logger.info(f"已移除订阅ID {subscribe_id} 的定时邮件任务") 