from functools import wraps
from threading import Semaphore, Timer


def rate_limit(secs: float):
    def decorator(fn):
        """This is the actual decorator that performs the rate-limiting."""
        semaphore = Semaphore(1)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            semaphore.acquire()
            try:
                return fn(*args, **kwargs)

            finally:  # ensure semaphore release
                timer = Timer(secs, semaphore.release)
                timer.setDaemon(True)  # allows the timer to be canceled on exit
                timer.start()

        return wrapper

    return decorator
