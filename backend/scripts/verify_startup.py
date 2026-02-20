
import sys
import os
import logging
import asyncio

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(os.path.join(project_root, 'backend'))

logger.info(f"Project Root: {project_root}")

try:
    logger.info("Step 1: Importing config...")
    from app import config
    logger.info(f"Config loaded. BIAS_WEIGHTS: {config.BIAS_WEIGHTS}")

    logger.info("Step 2: Importing app.main...")
    from app.main import app, lifespan
    logger.info("App imported successfully.")
    
    # Optional: Run lifespan manually?
    # Usually lifespan is async generator.
    
    logger.info("✅ Startup Verification Passed (Imports & Config OK)")

except Exception as e:
    logger.error(f"❌ Startup Failed: {e}", exc_info=True)
    sys.exit(1)
