import logging
import os
from typing import Any, Union, Mapping

# Placeholder for future configuration loading
# from .config.settings import get_settings
# settings = get_settings()

# --- Default AILogger Configuration ---
# These could be moved to a config file or environment variables later
AI_LOGGER_DEFAULT_LEVEL = os.environ.get("LOGLENS_DEFAULT_LEVEL", "INFO").upper()


class AILogger(logging.Logger):
    """
    AI-enhanced Logger class.
    This class extends the standard logging.Logger to integrate AI capabilities
    while preserving all out-of-the-box functionality of the standard logger.
    Users can switch to this logger with zero code changes by setting it as the
    default logger class using logging.setLoggerClass(AILogger).
    """

    def __init__(self, name: str, level: Union[int, str] = AI_LOGGER_DEFAULT_LEVEL) -> None:
        """
        Initialize the AILogger.
        Args:
            name: The name of the logger.
            level: The logging level.
        """
        super().__init__(name, level)
        # Add any AILogger-specific initialization here
        # For example, setting up specific handlers or filters by default,
        # though much of that will be driven by the AIHandler later.

    # All standard logging methods (debug, info, warning, error, critical,
    # exception, log) are inherited from logging.Logger.
    # We can override them if we need to add specific pre-processing
    # before the log record is created or handled, but for a "drop-in"
    # replacement that preserves all default features, direct overrides
    # of these might not be immediately necessary unless AILogger itself
    # needs to behave differently *before* records go to handlers.

    # Example of how one might override a method if needed:
    # def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
    #     # Custom logic before calling super().info()
    #     # For instance, adding some context automatically
    #     if self.isEnabledFor(logging.INFO):
    #         # The _log method is the internal method that actually creates LogRecord
    #         self._log(logging.INFO, msg, args, **kwargs)

    # The AILogger class will primarily serve as the entry point.
    # The actual AI processing, JSON formatting, batching, etc., will be
    # implemented in custom Handlers (like AIHandler) that are added to
    # instances of this AILogger.

    # Methods for setting level, adding/removing filters and handlers are
    # also inherited and should work as expected.


def get_ai_logger(name: str) -> AILogger:
    """
    Factory function to get an instance of AILogger.
    This function ensures that logging.setLoggerClass(AILogger) is called
    before the logger is retrieved, making AILogger the default for new loggers.

    Args:
        name: The name of the logger.

    Returns:
        An instance of AILogger.
    """
    original_logger_class = logging.getLoggerClass()
    if original_logger_class is not AILogger:
        logging.setLoggerClass(AILogger)

    logger = logging.getLogger(name)

    # Restore original logger class if it was changed,
    # to avoid side effects if other parts of an application
    # expect the standard Logger class.
    # However, for a true "drop-in" where loglens takes over,
    # we might want to leave it as AILogger.
    # For now, let's assume loglens is explicitly adopted.
    # If logging.setLoggerClass was called by user at app startup, this is fine.
    # If this get_ai_logger is the *only* way users get AILogger,
    # then we might not need to restore.
    # Consider application-wide setup:
    # import logging
    # from loglens.logger import AILogger
    # logging.setLoggerClass(AILogger)
    # logger = logging.getLogger(__name__) # will be an AILogger

    if not isinstance(logger, AILogger):
        # This can happen if the logger was already instantiated with a different class
        # before setLoggerClass(AILogger) took effect for this name.
        # In such cases, we might need to manually replace handlers or reconfigure.
        # For simplicity, we assume get_ai_logger is called for new loggers or
        # that setLoggerClass has been called globally at application startup.
        # A more robust solution might involve replacing the logger instance in
        # logging.Logger.manager.loggerDict if it's not an AILogger.
        # However, this is getting into deeper logging module internals.
        # The standard way is `logging.setLoggerClass(AILogger)` at the start.
        pass

    return logger  # type: ignore


# To make AILogger the default for all loggers created after this module is imported
# and setLoggerClass is called:
# logging.setLoggerClass(AILogger)
# This line can be called by the application at its entry point.
# Or, users can exclusively use `get_ai_logger`.

if __name__ == "__main__":
    # Example of setting AILogger as the default logger class
    # This should ideally be done at the very beginning of an application
    logging.setLoggerClass(AILogger)

    # Now, any logger obtained via logging.getLogger will be an AILogger instance
    logger1 = logging.getLogger("my_app.module1")
    logger2 = logging.getLogger("my_app.module2")

    print(f"Logger1 type: {type(logger1)}")
    print(f"Logger2 type: {type(logger2)}")

    # Test basic logging (will go to console by default if no handlers configured)
    # To see output, you might need a basicConfig or to add a handler.
    logging.basicConfig(level=logging.INFO)  # For basic console output

    logger1.info("This is an info message from logger1 (AILogger).")
    logger1.warning("This is a warning from logger1.")

    # Example of using the factory function
    # (setLoggerClass is already called, so this will also return AILogger)
    logger3 = get_ai_logger("my_app.module3")
    print(f"Logger3 type: {type(logger3)}")
    logger3.error("This is an error from logger3 (AILogger via factory).")

    # Verify that it's indeed an AILogger
    assert isinstance(logger1, AILogger)
    assert isinstance(logger3, AILogger)

    # Verify it's also a logging.Logger
    assert isinstance(logger1, logging.Logger)

    print("AILogger basic tests passed.")
