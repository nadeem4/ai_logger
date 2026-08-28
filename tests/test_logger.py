import logging

from logscribe.logger import AILogger, get_ai_logger


def test_ailogger_is_a_standard_logger_subclass():
    logger = AILogger("test.logger.direct_instantiation")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test.logger.direct_instantiation"


def test_get_ai_logger_sets_logger_class_and_returns_ailogger_instance():
    original_class = logging.getLoggerClass()
    try:
        logger = get_ai_logger("test.logger.get_ai_logger_unique")
        assert isinstance(logger, AILogger)
        assert logging.getLoggerClass() is AILogger
        # Once setLoggerClass(AILogger) has taken effect, a brand new logger
        # obtained through the plain stdlib API is also an AILogger.
        child = logging.getLogger("test.logger.get_ai_logger_unique.child")
        assert isinstance(child, AILogger)
    finally:
        logging.setLoggerClass(original_class)
        for name in list(logging.Logger.manager.loggerDict):
            if name.startswith("test.logger.get_ai_logger_unique"):
                del logging.Logger.manager.loggerDict[name]


def test_get_ai_logger_is_idempotent_when_class_already_set():
    original_class = logging.getLoggerClass()
    try:
        logging.setLoggerClass(AILogger)
        logger = get_ai_logger("test.logger.get_ai_logger_idempotent")
        assert isinstance(logger, AILogger)
    finally:
        logging.setLoggerClass(original_class)
        logging.Logger.manager.loggerDict.pop("test.logger.get_ai_logger_idempotent", None)
