import traceback
import main
import sys

try:
    main.capture_thread_func()
except Exception as e:
    with open('crash_log.txt', 'w') as f:
        f.write(traceback.format_exc())
