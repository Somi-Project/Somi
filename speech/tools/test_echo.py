"""Manual assisted Tier0 echo test.
1) Start run_speech with --echo-policy tier0.
2) Trigger assistant speech with mic open.
Expected: no STT calls while state is SPEAKING.
"""
print(__doc__)
