from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Form
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from scheduler import scheduler_manager

router = APIRouter()

@router.post("/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # 只检查邮箱是否重复
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="邮箱已被注册")
    
    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.post("/login", response_model=schemas.Token)
async def login_for_access_token(
    username: str = Form(...),  # 使用Form接收表单数据
    password: str = Form(...),  # 使用Form接收表单数据
    db: Session = Depends(get_db)
):
    # 使用邮箱查找用户
    user = db.query(models.User).filter(models.User.email == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/users/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user 

@router.get("/email-settings", response_model=schemas.UserSubscribeMail)
async def get_email_settings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 获取用户的邮件设置
    settings = db.query(models.UserSubscribeMail).filter(
        models.UserSubscribeMail.user_id == current_user.id
    ).first()
    
    if not settings:
        raise HTTPException(
            status_code=404,
            detail="未找到邮件设置"
        )
    
    return settings

@router.post("/email-settings", response_model=schemas.UserSubscribeMail)
async def create_email_settings(
    settings: schemas.UserSubscribeMailCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 检查是否已存在设置
    existing_settings = db.query(models.UserSubscribeMail).filter(
        models.UserSubscribeMail.user_id == current_user.id
    ).first()
    
    if existing_settings:
        raise HTTPException(
            status_code=400,
            detail="邮件设置已存在"
        )
    
    # 创建新的设置
    db_settings = models.UserSubscribeMail(
        user_id=current_user.id,
        email=settings.email,
        word_count=settings.word_count,
        send_time=settings.send_time
    )
    
    db.add(db_settings)
    db.commit()
    db.refresh(db_settings)
    
    # 添加定时任务
    scheduler_manager.schedule_user_email(db_settings)
    
    return db_settings

@router.put("/email-settings", response_model=schemas.UserSubscribeMail)
async def update_email_settings(
    settings: schemas.UserSubscribeMailCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 获取现有设置
    db_settings = db.query(models.UserSubscribeMail).filter(
        models.UserSubscribeMail.user_id == current_user.id
    ).first()
    
    if not db_settings:
        raise HTTPException(
            status_code=404,
            detail="未找到邮件设置"
        )
    
    # 更新设置
    db_settings.email = settings.email
    db_settings.word_count = settings.word_count
    db_settings.send_time = settings.send_time
    
    db.commit()
    db.refresh(db_settings)
    
    # 更新定时任务
    scheduler_manager.schedule_user_email(db_settings)
    
    return db_settings

@router.delete("/email-settings", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_settings(
    id: int,
    db: Session = Depends(get_db)
):
    # 获取邮件设置
    db_settings = db.query(models.UserSubscribeMail).filter(
        models.UserSubscribeMail.id == id
    ).first()
    
    if not db_settings:
        raise HTTPException(
            status_code=404,
            detail="未找到邮件设置"
        )
    
    # 移除定时任务
    scheduler_manager.remove_job(db_settings.id)
    
    # 删除设置
    db.delete(db_settings)
    db.commit()
    
    return None 