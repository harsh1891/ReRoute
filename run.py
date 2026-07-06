from app.server import app

if __name__ == '__main__':
    print("==================================================")
    print("   ReRoute: Passenger Re-accommodation Console")
    print("==================================================")
    print("Starting Flask web server on http://localhost:5000")
    print("Press CTRL+C to stop.")
    app.run(debug=True, port=5000)
