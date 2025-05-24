import logging

def get_logger(name):
    """
    Get a logger configured with the application's settings.
    
    Args:
        name (str): The name of the module requesting the logger
        
    Returns:
        logging.Logger: A configured logger instance
    """
    return logging.getLogger(name)


def log_function_call(logger, func_name, args=None, kwargs=None):
    """
    Utility to log function calls with their arguments.
    
    Args:
        logger (logging.Logger): The logger to use
        func_name (str): Name of the function being called
        args (tuple, optional): Positional arguments
        kwargs (dict, optional): Keyword arguments
    """
    args_str = str(args) if args else "no positional args"
    kwargs_str = str(kwargs) if kwargs else "no keyword args"
    logger.debug(f"Called {func_name} with args: {args_str}, kwargs: {kwargs_str}")


def setup_module_logger(module_name):
    """
    Convenience function to set up a logger for a module.
    
    Args:
        module_name (str): The name of the module (__name__)
        
    Returns:
        logging.Logger: A configured logger for the module
    """
    logger = logging.getLogger(module_name)
    
    # You can add module-specific configuration here if needed
    
    return logger