"""Codex local rollout ingestion: only user-facing assistant messages."""
import json
import queue
from pathlib import Path

import pytest

from agent_tts import parser
from agent_tts.application.controller import Controller
from agent_tts.ingest import transcript
from tests.test_application import FakePlayer, pump


def message(text='KIRA: Hello from Codex.', phase='final_answer', ident='reply-1'):
    return {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
            'id': ident, 'phase': phase, 'content': [{'type': 'output_text', 'text': text}]}}


@pytest.mark.parametrize('event', [
    {'type': 'response_item', 'payload': {'type': 'reasoning', 'content': [{'type': 'output_text', 'text': 'secret'}]}},
    {'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'duplicate'}},
    {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'output_text', 'text': 'user'}]}},
    message(phase='analysis'),
    {'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': 'tool'}},
])
def test_ignores_non_user_facing_output(event):
    assert transcript._extract_assistant_text(event, True) is None


def test_progress_is_opt_in_and_final_formats_work():
    assert transcript._extract_assistant_text(message(phase='commentary')) is None
    assert transcript._extract_assistant_text(message(phase='commentary'), True)
    for phase in ('final_answer', 'final', None):
        assert transcript._extract_assistant_text(message(phase=phase)) == 'KIRA: Hello from Codex.'


def test_kira_written_detail_is_an_aside():
    blocks = parser.parse('KIRA: The call.\n\n> Written details only.\n\nKIRA: Next action.')
    assert [(b.speaker, b.text) for b in blocks] == [
        ('KIRA', 'The call.'), (parser.ASIDE, 'Written details only.'), ('KIRA', 'Next action.')]


def test_both_sources_read_new_messages_without_duplicate_speech(make_cfg, tmp_path, monkeypatch):
    from agent_tts import config
    from agent_tts.application.drafts import Drafts
    claude = tmp_path / 'claude' / 'project'; claude.mkdir(parents=True)
    codex = tmp_path / 'codex' / '2026' / '10' / '15'; codex.mkdir(parents=True)
    cp, xp = claude / 'session.jsonl', codex / 'rollout-test.jsonl'
    cp.write_text(''); xp.write_text(json.dumps(message('Old history'))+'\n')
    monkeypatch.setattr(transcript, '_CLAUDE_DIR', claude.parent)
    monkeypatch.setattr(transcript, '_CODEX_DIR', tmp_path / 'codex')
    cfg_path = tmp_path / 'voices.yaml'; config.save(make_cfg(), cfg_path)
    spoken = []

    class Pool:
        def __init__(self, cfg): pass
        def preflight(self): pass
        def get(self, provider): return self
        def synth(self, text, voice, settings):
            spoken.append(text)
            return Path('sample.wav')

    results = queue.Queue(); events = []
    controller = Controller(Drafts(cfg_path), results.put, lambda *args: events.append(args),
                            enable_hotkeys=False, player_factory=FakePlayer, pool_factory=Pool)
    try:
        controller.start(source='both')
        pump(controller, results, lambda: sum(k=='session' for k,d in events)==2)
        with cp.open('a') as f:
            f.write(json.dumps({'type':'assistant','uuid':'c1','message':{'content':[{'type':'text','text':'KIRA: Claude reply.'}]}})+'\n')
        with xp.open('a') as f:
            reply=message('KIRA: Codex reply.', ident='new')
            for event in (message('Progress', 'commentary', 'progress'), reply, reply):
                f.write(json.dumps(event)+'\n')
        pump(controller, results, lambda: len(controller._player.items)==2)
        assert sorted(spoken)==['Claude reply.', 'Codex reply.']
        controller.stop()
        for thread in controller._tail_threads: thread.join(1)
        assert not any(thread.is_alive() for thread in controller._tail_threads)
    finally:
        controller.close()
        controller._synth_thread.join(1)


def test_follow_new_concurrent_sessions_and_partial_records(tmp_path, monkeypatch):
    import threading
    import time
    monkeypatch.setattr(transcript, '_CODEX_DIR', tmp_path)
    stop, ready = threading.Event(), threading.Event()
    output=[]
    worker=threading.Thread(target=lambda: output.extend(transcript.follow('codex', stop_event=stop,
        poll_interval=.01, on_ready=lambda _: ready.set())))
    worker.start()
    try:
        assert ready.wait(1)
        a=tmp_path/'rollout-a.jsonl'; b=tmp_path/'rollout-b.jsonl'
        line=json.dumps(message('KIRA: First.', ident='first'))+'\n'
        a.write_text(line[:40])
        b.write_text(json.dumps(message('KIRA: Second.', ident='second'))+'\n')
        time.sleep(.04)
        assert output == ['KIRA: Second.']
        with a.open('a') as f: f.write(line[40:])
        deadline=time.monotonic()+1
        while len(output)<2 and time.monotonic()<deadline: time.sleep(.01)
        assert sorted(output)==['KIRA: First.', 'KIRA: Second.']
    finally:
        stop.set(); worker.join(1)
    assert not worker.is_alive()


def test_unreadable_session_does_not_stop_healthy_session(tmp_path, monkeypatch):
    import threading
    import time
    monkeypatch.setattr(transcript, '_CODEX_DIR', tmp_path)
    bad=tmp_path/'rollout-bad.jsonl'; bad.write_text('')
    good=tmp_path/'rollout-good.jsonl'; good.write_text('')
    stop,ready=threading.Event(),threading.Event();output=[];errors=[]
    original=Path.open
    def open_file(path,*args,**kwargs):
        if path==bad: raise PermissionError('test')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',open_file)
    worker=threading.Thread(target=lambda: output.extend(transcript.follow('codex',stop_event=stop,
        poll_interval=.01,on_ready=lambda _:ready.set(),on_error=errors.append)))
    worker.start()
    try:
        assert ready.wait(1)
        # Give the inaccessible file unread bytes without using Path.open.
        with open(bad,'w') as f: f.write('blocked\n')
        good.write_text(json.dumps(message())+'\n')
        deadline=time.monotonic()+1
        while (not output or not errors) and time.monotonic()<deadline: time.sleep(.01)
        assert output==['KIRA: Hello from Codex.']
        assert errors
    finally:
        stop.set();worker.join(1)


@pytest.mark.parametrize('event', [
    {'type':'response_item','payload':None},
    {'type':'response_item','payload':{'type':'message','role':'assistant','content':None}},
    {'type':'assistant','message':None},
    {'type':'assistant','message':{'content':'wrong'}},
])
def test_malformed_record_is_ignored(event):
    assert transcript._extract_assistant_text(event,True) is None


def test_new_fork_does_not_replay_history(tmp_path, monkeypatch):
    import threading
    import time
    monkeypatch.setattr(transcript,'_CODEX_DIR',tmp_path)
    stop,ready=threading.Event(),threading.Event();output=[]
    worker=threading.Thread(target=lambda: output.extend(transcript.follow('codex',stop_event=stop,
        poll_interval=.01,on_ready=lambda _:ready.set())))
    worker.start()
    try:
        assert ready.wait(1)
        first=message('Live reply',ident='live')
        (tmp_path/'rollout-original.jsonl').write_text(json.dumps(first)+'\n')
        deadline=time.monotonic()+1
        while not output and time.monotonic()<deadline:time.sleep(.01)
        assert output==['Live reply']
        old=message('Old copied history',ident='old');old['timestamp']='2020-01-01T00:00:00Z'
        fork=tmp_path/'rollout-fork.jsonl'
        fork.write_text('\n'.join(json.dumps(e) for e in (old,first,{'type':'response_item','payload':None},message('New fork reply',ident='new')))+'\n')
        deadline=time.monotonic()+1
        while len(output)<2 and time.monotonic()<deadline:time.sleep(.01)
        assert output==['Live reply','New fork reply']
    finally:stop.set();worker.join(1)
