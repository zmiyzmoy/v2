# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
# Create a requirements.txt file or add individual pip installs here
RUN pip install --no-cache-dir fastapi uvicorn python-telegram-bot requests httpx

# Copy the rest of the application code into the container at /app
COPY ./main.py /app/main.py

# Make port 8002 available to the world outside this container
EXPOSE 8002

# Run main.py when the container launches
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
