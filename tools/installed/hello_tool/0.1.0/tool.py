from datetime import datetime


def run(args, ctx):
    name = args.get("name", "friend")
    return {"message": f"Hello {name}", "time": datetime.utcnow().isoformat() + "Z"}
