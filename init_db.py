# init_db.py
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings
from app.models.user import get_password_hash



async def init_db():
    print("正在初始化数据库...")
    engine = create_async_engine(settings.DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        # 创建所有表（使用原始 SQL 会更好，但这里我们使用 metadata）
        from app.database.base import Base
        await conn.run_sync(Base.metadata.create_all)

        # 1. 插入租户（如果不存在）
        result = await conn.execute(
            text("SELECT id FROM tenants WHERE name = 'DefaultCompany'")
        )
        tenant_row = result.fetchone()
        if tenant_row:
            tenant_id = tenant_row[0]
        else:
            await conn.execute(
                text("INSERT INTO tenants (name, description) VALUES ('DefaultCompany', '默认企业')")
            )
            result = await conn.execute(text("SELECT LAST_INSERT_ID()"))
            tenant_id = result.scalar()

        # 2. 插入角色
        roles = ["super_admin", "tenant_admin", "member", "viewer"]
        role_ids = {}
        for role_name in roles:
            result = await conn.execute(text("SELECT id FROM roles WHERE name = :name"), {"name": role_name})
            row = result.fetchone()
            if row:
                role_ids[role_name] = row[0]
            else:
                await conn.execute(text("INSERT INTO roles (name, is_system) VALUES (:name, 1)"), {"name": role_name})
                result = await conn.execute(text("SELECT LAST_INSERT_ID()"))
                role_ids[role_name] = result.scalar()

        # 3. 创建超级管理员
        result = await conn.execute(text("SELECT id FROM users WHERE username = 'admin'"))
        admin_row = result.fetchone()
        if not admin_row:
            hashed_pw = get_password_hash("Admin123!")
            await conn.execute(
                text("""
                     INSERT INTO users (username, email, hashed_password, tenant_id, is_superuser, is_active)
                     VALUES ('admin', 'admin@example.com', :pw, :tenant_id, 1, 1)
                     """),
                {"pw": hashed_pw, "tenant_id": tenant_id}
            )
            result = await conn.execute(text("SELECT LAST_INSERT_ID()"))
            admin_id = result.scalar()
            # 分配 super_admin 角色
            await conn.execute(
                text("INSERT INTO user_roles (user_id, role_id, tenant_id) VALUES (:uid, :rid, :tid)"),
                {"uid": admin_id, "rid": role_ids["super_admin"], "tid": tenant_id}
            )

    print("数据库初始化完成！")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())