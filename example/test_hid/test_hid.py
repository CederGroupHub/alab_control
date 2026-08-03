import keyboard

cache = []
current_value = None

def get_input():
    global cache
    while True:
        event = keyboard.read_event()
        print(event)
        if event.event_type == 'down':
            if event.name == 'enter':
                result = cache.copy()
                cache.clear()
                return result
            else:
                cache.append(event.name)


if __name__ == '__main__':
    while True:
        print(get_input())