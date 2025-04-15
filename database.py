from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 从环境变量获取数据库连接URL
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# 配置数据库引擎，添加连接池和重连机制
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # 启用连接检查
    pool_recycle=3600,   # 每隔1小时回收连接
    pool_size=5,         # 连接池大小
    max_overflow=10,     # 最大溢出连接数
    pool_timeout=30,     # 连接池获取连接的超时时间
    echo=False           # 是否打印SQL语句，生产环境建议关闭
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 依赖项
def get_db():
    db = SessionLocal()
    try:
        # 测试连接是否有效
        db.execute("SELECT 1")
        yield db
    except Exception as e:
        # 如果连接失败，尝试重新创建连接
        db = SessionLocal()
        yield db
    finally:
        db.close() 