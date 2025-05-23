# XRLab_autograder_v2

## Project Overview

XR Autograder V2 is a web-based application designed to assist instructors in grading student assignments, particularly for subjects like architecture where submissions are often PDF documents containing a mix of text and visual elements. The system leverages Google's Gemini AI (specifically the multimodal `gemini-1.5-flash-latest` model) to perform a "hybrid" evaluation: analyzing both the full extracted text of a submission and key page images.

The core idea is to provide an iterative grading workflow where the instructor can:
1.  Define and refine a detailed rubric prompt.
2.  Test the rubric on sample student submissions.
3.  Get explanations from the AI about its scoring.
4.  Manage reusable feedback snippets.
5.  Process student submissions individually or in batches.
6.  Export grading results.

## Features

### Student Interface:
* Simple web form for students to submit their name, PID, architect name (assignment context), and PDF assignment.
* Receives immediate feedback, including a grade, percentage score, individual rubric scores, a summary of AI-generated feedback, and the detailed AI evaluation.

### Admin Interface (Password Protected):
* **Dashboard/Submissions Tab:**
    * View all student submissions with key details (name, PID, grade, score, timestamp).
    * View detailed evaluation results for each submission in a modal, including all scores and feedback.
    * Export all submission data as CSV or JSON.
* **Rubric & Testing Tab:**
    * View and edit the master rubric prompt (`current_rubric_hybrid.txt`) used for AI evaluation.
    * Save changes to the rubric prompt.
    * Test the current rubric by uploading a sample PDF and providing context (e.g., architect name).
    * View detailed sample evaluation results:
        * Breakdown of scores for each rubric criterion.
        * Button to get an AI-generated explanation for specific scores/feedback on a criterion.
        * The full textual detailed evaluation from the AI.
        * The raw AI response (for debugging).
    * Save selected text from the AI's detailed evaluation as a reusable feedback snippet.
* **Batch Processing Tab:**
    * Upload multiple student PDF assignments simultaneously.
    * Provide a default architect name (or assignment theme) for the batch.
    * Initiate batch grading using the current finalized rubric.
    * View a summary of the batch processing results (successes, errors).
* **Feedback Snippets Tab:**
    * View a list of all saved reusable feedback snippets.
    * Add new snippets manually.
    * Edit the name and content of existing snippets.
    * Delete snippets.
    * Insert snippet content directly into the main rubric prompt textarea for quick editing.

### Core Logic:
* **Hybrid Evaluation:**
    * Extracts full text from the submitted PDF.
    * Selects a configurable number of key page images from the PDF (e.g., first, last, sampled middle pages).
    * Sends both the full text and key page images to the Gemini 1.5 Flash multimodal model along with the detailed rubric prompt.
    * The AI evaluates based on instructions to use text for content-based criteria and images for visual/layout criteria.
* **Score Parsing:** Parses scores from a Markdown table (`**Summary of Scores:**`) expected at the end of the AI's detailed evaluation response.
* **Explanation Generation:** Uses Gemini's text model to provide explanations for specific scores when requested by the admin, using the original rubric and evaluation feedback as context.
* **Student-Facing Feedback Summary:** Generates a concise summary of feedback for the student based on the AI's detailed evaluation.


## Project Structure


autograder_v2/
|   |-- .env                   # Environment variables (GEMINI_API_KEY, admin credentials)
|   |-- autograder_backend_v2.py # Flask backend application
|   |-- autograder_logic_v2.py   # Core AI interaction and grading logic
|   |-- feedback_snippets.json   # Stores reusable feedback snippets (created on first save)
|   |-- rubric_prompts/
|   |   |-- current_rubric_hybrid.txt # The main rubric prompt for hybrid evaluation
|   |-- static/                  # Static files (if CSS/JS are moved external)
|   |   |-- css/
|   |   |-- js/
|   |-- templates/
|   |   |-- admin_v2.html        # Admin dashboard interface
|   |   |-- frontend_v2.html     # Student submission interface
|   |-- submissions_v2/          # Stores JSON files of graded student submissions
|   |-- uploads_v2/              # Temporary storage for uploaded PDFs during processing

## Setup and Installation

1.  **Prerequisites:**
    * Python 3.8+
    * Access to Google Gemini API and an API Key.

2.  **Clone the Repository (if applicable) or Create Directory Structure:**
    Ensure you have the `autograder_v2` directory and its subdirectories as listed above.

3.  **Create a Python Virtual Environment:**
    Navigate to the `XR_Lab` directory (or your main project root).
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

4.  **Install Dependencies:**
    Create a `requirements.txt` file inside the `autograder_v2` directory (or at the project root) with the following content:
    ```txt
    Flask
    Flask-CORS
    python-dotenv
    google-generativeai
    PyMuPDF
    Pillow
    werkzeug
    csv # (Standard library, but good to note if a specific version was ever needed)
    ```
    Install them:
    ```bash
    pip install -r requirements.txt # (Adjust path to requirements.txt if needed)
    ```

5.  **Set up Environment Variables:**
    Create a file named `.env` inside the `autograder_v2` directory (`autograder_v2/.env`). Add the following, replacing placeholders with your actual values:
    ```env
    GEMINI_API_KEY="YOUR_GOOGLE_GEMINI_API_KEY"
    ADMIN_USERNAME="your_admin_username"
    ADMIN_PASSWORD="your_strong_admin_password"
    # FLASK_APP="autograder_backend_v2.py" # Optional, can help Flask CLI
    # FLASK_DEBUG=True # For development
    ```

6.  **Prepare Rubric Prompt:**
    * Ensure the rubric prompt file exists at `autograder_v2/rubric_prompts/current_rubric_hybrid.txt`.
    * The content of this file should be the detailed rubric and instructions for the AI, including the final instruction to output scores in a Markdown table. Refer to the provided code for the correct structure.

7.  **Place HTML Files:**
    * `admin_v2.html` and `frontend_v2.html` should be in the `autograder_v2/templates/` directory.

## Running the Application

1.  **Activate Virtual Environment:**
    ```bash
    source venv/bin/activate  # Or venv\Scripts\activate on Windows
    ```
2.  **Navigate to the Project Root Directory:**
    This is the directory that *contains* the `autograder_v2` folder (e.g., `/Users/tanishqsingh/Desktop/XR_Lab/`).
3.  **Run the Flask Application:**
    ```bash
    python -m autograder_v2.autograder_backend_v2
    ```
    The server should start, typically on `http://127.0.0.1:5001/` and also accessible via your local network IP.

4.  **Accessing the Interfaces:**
    * **Student Submission Page:** Open a web browser and go to `http://localhost:5001/`
    * **Admin Dashboard:** Open a web browser and go to `http://localhost:5001/admin` (you will be prompted for the admin username and password defined in your `.env` file).

## Usage Workflow (Admin)

1.  **Login:** Access `/admin` and log in.
2.  **Configure Rubric:**
    * Navigate to the "Rubric & Testing" tab.
    * Click "Load Current Rubric" to view/edit the `current_rubric_hybrid.txt` content.
    * Make any necessary modifications to the prompt. Remember that this prompt guides the AI's entire hybrid evaluation process.
    * Click "Save Rubric" to persist changes.
3.  **Test Rubric:**
    * Still in the "Rubric & Testing" tab, upload a sample student PDF.
    * Enter the relevant "Architect Name" (or other context required by your rubric placeholders like `{architect_name}`).
    * Click "Test with Sample."
    * Review the "Sample Evaluation Results":
        * Check the scores and the feedback breakdown.
        * If a score or feedback is unclear, click the "Explain" button next to it to get more details from the AI.
        * Examine the "Full Detailed AI Evaluation Text" and the "Raw Gemini Response" for deeper insights or debugging.
    * If the evaluation is not as expected, iterate: modify the rubric prompt, save it, and re-test the sample until satisfied.
4.  **Manage Feedback Snippets (Optional but Recommended):**
    * While reviewing sample evaluations (or later, actual submissions), if you see good reusable feedback from the AI, select the text in the "Full Detailed AI Evaluation Text" area and click "Save Selected as Snippet."
    * Navigate to the "Feedback Snippets" tab to view, edit, or delete snippets.
    * You can also add snippets manually here.
    * Use the "Insert in Rubric" button to quickly add snippet content to your main rubric prompt if you're building up standard feedback phrases.
5.  **Batch Grade Submissions:**
    * Once the rubric is finalized and tested, navigate to the "Batch Processing" tab.
    * Select multiple student PDF files.
    * Provide a default "Architect Name" if applicable for the batch.
    * Click "Start Batch Grading." Monitor the progress.
6.  **Review Submissions & Export:**
    * Go to the "Submissions" tab. Click "Refresh Submissions."
    * View details of individual submissions. At this stage, manual editing of saved feedback is a potential future feature.
    * Use "Export All as CSV" or "Export All as JSON" to get the grading data.

