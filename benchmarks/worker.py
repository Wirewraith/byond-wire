import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from byond_wire import topic, topic_raw

host, port = sys.argv[1], int(sys.argv[2])
for line in sys.stdin:
    mode, query, _ = line.rstrip('\n').split('\t')
    start = time.perf_counter_ns()
    try:
        value = (topic_raw if mode == 'raw' else topic)(host, port, query)
        ms = (time.perf_counter_ns() - start) / 1e6
        kind = 'null' if value is None else 'number' if isinstance(value, float) else 'text'
        if kind == 'text' and not isinstance(value, bytes if mode == 'raw' else str):
            raise ValueError('incorrect native text type')
        size = 0 if value is None else 4 if kind == 'number' else len(value.encode() if isinstance(value, str) else value)
        print(ms, kind, size, sep='\t', flush=True)
    except Exception as error:
        print((time.perf_counter_ns() - start) / 1e6, 'error', type(error).__name__ + ': ' + str(error).replace('\n', ' '), sep='\t', flush=True)
