
import uvicorn
import os

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8007))
    uvicorn.run("question_agent.app:create_app", host="0.0.0.0", port=port, factory=True)
