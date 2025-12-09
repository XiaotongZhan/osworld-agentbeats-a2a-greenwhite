# white_sim/server.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="White Agent Baseline")

@app.get("/card")
def card():
    return {"name":"white-baseline","version":"0.0.1","policy":"baseline-scroll-then-wait"}

@app.post("/reset")
def reset():
    global _calls
    _calls = 0
    return {"reset":"ok"}

_calls = 0

@app.post("/act")
def act(payload: dict):
    # Extremely naive: WAIT -> SCROLL -> WAIT -> DONE
    global _calls
    _calls += 1
    if _calls == 1:
        return JSONResponse(content={"type":"special","name":"WAIT","pause":0.8})
    if _calls == 2:
        # pyautogui runs inside OSWorld VM via Green -> DesktopEnv.step
        return JSONResponse(content={"type":"code","code":"import pyautogui; pyautogui.scroll(-400)","pause":0.5})
    if _calls == 3:
        return JSONResponse(content={"type":"special","name":"WAIT","pause":0.5})
    return JSONResponse(content={"type":"special","name":"DONE","pause":0.0})