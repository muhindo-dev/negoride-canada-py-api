from datetime import datetime


def greet():
    """Time-based greeting matching Laravel's Utils::greet()"""
    hour = datetime.now().hour
    if hour < 12:
        return "Good Morning"
    elif hour < 17:
        return "Good Afternoon"
    else:
        return "Good Evening"


def my_date_time(dt):
    """Format datetime matching Laravel's Utils::my_date_time()"""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def my_date(dt):
    """Format date matching Laravel's Utils::my_date()"""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.strftime('%Y-%m-%d')
