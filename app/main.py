"""Main FastAPI application entry point."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.bot.bot import dp, bot
from app.database.connection import init_db
from app.bot.handlers import patient


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print("🚀 Starting application...")
    
    # Initialize database
    await init_db()
    print("✅ Database initialized")
    
    # Include bot routers
    dp.include_router(patient.router)
    print("✅ Bot handlers registered")
    
    # Start bot polling in background
    asyncio.create_task(dp.start_polling(bot))
    print("✅ Bot polling started")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down...")
    await bot.session.close()


# Create FastAPI app
app = FastAPI(
    title="Dental Clinic Queue Management",
    description="Telegram bot for managing dental clinic queues",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Dental Clinic Queue Management Bot",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
