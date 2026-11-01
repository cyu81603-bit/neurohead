"""Independent reply and intent routes; no model, audio, or hardware ownership."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED


def turn_results(reply_call,action_call,cancelled=lambda:False):
    executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='dialogue-route')
    routes={executor.submit(reply_call):'reply',executor.submit(action_call):'action_decision'}
    pending=set(routes)
    try:
        while pending:
            if cancelled():return
            done,pending=wait(pending,timeout=.05,return_when=FIRST_COMPLETED)
            for future in done:
                if cancelled():return
                try:result=future.result()
                except Exception as exc:yield routes[future],None,exc
                else:yield routes[future],result,None
    finally:
        executor.shutdown(wait=False,cancel_futures=True)
