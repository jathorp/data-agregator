# src/app.py          <-- keep it at the top level of the ZIP
# Handler path:  app.handler
#
# What it does:
#   • Logs the incoming event to CloudWatch
#   • Returns a simple string so you can see a response

def handler(event, context):
    """
    Minimal AWS Lambda handler.
    Prints whatever event the service passes in and returns a fixed string.
    """
    print("🪵 Received event:", event)          # Shows up in CloudWatch Logs
    return "✅ Lambda executed successfully"
