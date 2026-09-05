import uvicorn


if __name__ == "__main__":
    uvicorn.run("printer_fleet.api:app", host="0.0.0.0", port=8000)
