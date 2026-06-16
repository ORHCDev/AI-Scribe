import logging
from logging.handlers import TimedRotatingFileHandler
import os

def setup_daily_logger(log_dir, log_filename):
    """
    Creates a daily rotating log file handler which logs everything
    at INFO level or above, rotating at midnight.
    """
    # Ensure the log directory exists
    os.makedirs(log_dir, exist_ok=True)

    # Construct the full path for the log file
    full_path = os.path.join(log_dir, log_filename)

    # Create a timed rotating file handler
    # - `when='midnight'` rotates at midnight
    # - `interval=1` means one file per day
    # - `backupCount=7` means keep 7 days of logs, delete older ones
    handler = TimedRotatingFileHandler(
        filename=full_path,
        when='midnight',
        interval=1,
        backupCount=14
    )
    handler.setLevel(logging.INFO)

    # Format log entries with time, level, and message
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    # Configure the root logger to use this handler
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers so we don't double-log
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(handler)

    # (Optional) If certain library logs are too noisy, you can reduce them like so:
    # logging.getLogger("urllib3").setLevel(logging.WARNING)
    # or logging.getLogger("selenium").setLevel(logging.WARNING)