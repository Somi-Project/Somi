"""Manual assisted test for barge-in.
1) Start run_speech.
2) Prompt assistant for a long response.
3) Speak loudly during playback.
Expected: audio stops immediately and stale chunks are dropped.
"""
print(__doc__)
