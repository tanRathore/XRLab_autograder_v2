import os
import re
import fitz  # PyMuPDF
from PIL import Image, UnidentifiedImageError # Added UnidentifiedImageError
from io import BytesIO
import google.generativeai as genai
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env")

genai.configure(api_key=GEMINI_API_KEY)

try:
    # Gemini 1.5 Flash is good for multimodal inputs (text + images)
    multimodal_eval_model = genai.GenerativeModel("gemini-1.5-flash-latest")
    text_model = genai.GenerativeModel("gemini-1.5-flash-latest") # For explanations, summaries
except Exception as e:
    print(f"Error initializing GenerativeModel: {e}")
    raise

CATEGORY_TO_INTERNAL_KEY_MAP = {
    "Architect Selection & Scope": "architect_chosen",
    "Organization & Document Setup": "doc_and_slides",
    "Biographical Content": "bio_750_words",
    "Citation of Architect Bio": "bio_references",
    "Selection & Quality of Images": "image_quality",
    "Image Citation & Attribution": "image_citations",
    "Coverage of 10 Famous Buildings": "10_buildings_with_images",
    "Image Relevance": "image_relevance",
    "Personal Bio & Photo": "personal_bio_photo",
    "Overall Completeness & Presentation": "presentation_polish"
}
DEFAULT_INTERNAL_RUBRIC_KEYS = list(CATEGORY_TO_INTERNAL_KEY_MAP.values())

# --- NEW: Text Extraction Function ---
def extract_full_text_from_pdf(pdf_path):
    """Extracts all text content from a PDF file."""
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text += page.get_text("text") # Get plain text
            text += "\n--- End of Page {} ---\n".format(page_num + 1) # Add page delimiter
        doc.close()
        print(f"Successfully extracted full text from '{pdf_path}' ({len(text)} characters).")
    except Exception as e:
        print(f"Error extracting full text from PDF '{pdf_path}': {e}")
        text = "Error: Could not extract text from PDF."
    return text

# --- NEW: Key Page Image Selection Function (Basic Strategy) ---
def select_key_page_images(pdf_path, num_images_to_select=10, dpi=100): # Lowered DPI for key images
    """
    Selects a few key pages from the PDF and returns them as PIL Image objects.
    Basic strategy: first, last, and a few evenly sampled in-between pages.
    """
    selected_images = []
    doc = None # Initialize doc to None
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        if total_pages == 0:
            return selected_images

        pages_to_get_indices = set()

        # Add first page
        if total_pages > 0:
            pages_to_get_indices.add(0)

        # Add last page (if different from first)
        if total_pages > 1:
            pages_to_get_indices.add(total_pages - 1)
        
        # Add some sampled pages from the middle, if we need more images
        # Ensure we don't exceed num_images_to_select
        remaining_slots = num_images_to_select - len(pages_to_get_indices)
        if remaining_slots > 0 and total_pages > 2:
            # Sample from pages excluding first and last
            middle_pages_indices = list(range(1, total_pages - 1))
            if len(middle_pages_indices) > 0:
                step = max(1, len(middle_pages_indices) // remaining_slots)
                for i in range(0, len(middle_pages_indices), step):
                    if len(pages_to_get_indices) < num_images_to_select:
                        pages_to_get_indices.add(middle_pages_indices[i])
                    else:
                        break
        
        # Ensure we don't have too many if initial set was already large
        final_indices = sorted(list(pages_to_get_indices))[:num_images_to_select]

        print(f"Selected page indices for image extraction: {final_indices} (Target: {num_images_to_select})")

        for page_index in final_indices:
            if page_index < total_pages: # Ensure index is valid
                page = doc.load_page(page_index)
                pix = page.get_pixmap(dpi=dpi)
                try:
                    img = Image.open(BytesIO(pix.tobytes("png")))
                    selected_images.append(img)
                except UnidentifiedImageError:
                    print(f"Warning: Could not identify image from page {page_index + 1}. Skipping.")
                except Exception as e_img:
                    print(f"Warning: Error processing image from page {page_index + 1}: {e_img}. Skipping.")

    except Exception as e:
        print(f"Error selecting key page images from '{pdf_path}': {e}")
    finally:
        if doc:
            doc.close()
            
    print(f"Extracted {len(selected_images)} key page images.")
    return selected_images

def load_rubric_prompt_from_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"FATAL ERROR: Rubric prompt file not found at {filepath}")
        raise
    except Exception as e:
        print(f"Error reading rubric prompt file {filepath}: {e}")
        raise

def parse_scores_from_markdown_table(gemini_text_response, category_map, default_internal_keys):
    # This function remains the same as the last version you confirmed working
    scores_dict = {key: 0 for key in default_internal_keys}
    textual_evaluation = gemini_text_response
    summary_section_match = re.search(
        r"\*\*Summary of Scores:\*\*\s*\n(.*?)(?:\n\n\n|\Z)",
        gemini_text_response, re.DOTALL | re.IGNORECASE
    )
    if summary_section_match:
        table_content = summary_section_match.group(1).strip()
        textual_evaluation = gemini_text_response[:summary_section_match.start()].strip()
        row_pattern = re.compile(r"\|\s*(.+?)\s*\|\s*(\d+)\s*/\s*5\s*\|")
        found_any_score_in_table = False
        for line in table_content.splitlines():
            line = line.strip()
            if not line.startswith("|") or not line.endswith("|"): continue
            match = row_pattern.search(line)
            if match:
                category_from_table = match.group(1).strip()
                score_value = int(match.group(2))
                internal_key = category_map.get(category_from_table)
                if internal_key:
                    if internal_key in scores_dict:
                        scores_dict[internal_key] = score_value
                        found_any_score_in_table = True
                    else: print(f"Warning: Category '{category_from_table}' mapped to '{internal_key}', but key not in defaults.")
                else: print(f"Warning: Unrecognized category '{category_from_table}' in table.")
        if not found_any_score_in_table and table_content:
             print("Warning: 'Summary of Scores' table found, but no valid score rows parsed.")
    else:
        print("Warning: '**Summary of Scores:**' Markdown table not found.")
    return scores_dict, textual_evaluation

# --- MODIFIED: For Hybrid Evaluation ---
def gemini_evaluate_assignment_hybrid(
    full_pdf_text,
    key_page_images, # List of PIL.Image objects
    architect_name,
    rubric_prompt_template_text, # This is the new hybrid rubric
    num_selected_images
    ):
    """
    Sends full text and selected key page images to Gemini for a hybrid evaluation.
    """
    print(f"Starting Gemini Hybrid evaluation for architect '{architect_name}'")
    
    if not full_pdf_text and not key_page_images:
        error_msg = "Error: No text or images provided for hybrid evaluation."
        print(error_msg)
        return f"{error_msg}\n\n**Summary of Scores:**\n\n(No scores due to missing input)"

    # Substitute placeholders in the rubric prompt
    current_rubric_prompt = rubric_prompt_template_text.format(
        architect_name=architect_name,
        num_selected_images=len(key_page_images) # Inform AI how many images it's getting
    )
    
    # Construct prompt parts: text first, then images
    prompt_parts = [current_rubric_prompt]
    
    if full_pdf_text:
        prompt_parts.append("\n\n--- START OF FULL EXTRACTED TEXT ---\n")
        prompt_parts.append(full_pdf_text)
        prompt_parts.append("\n--- END OF FULL EXTRACTED TEXT ---\n")
    else:
        prompt_parts.append("\n\n(No full text extracted or provided for this document.)\n")

    if key_page_images:
        prompt_parts.append("\n--- START OF SELECTED PAGE IMAGES ---\n")
        for i, img in enumerate(key_page_images):
            prompt_parts.append(f"\nSelected Page Image {i+1} of {len(key_page_images)}:\n")
            prompt_parts.append(img)
        prompt_parts.append("\n--- END OF SELECTED PAGE IMAGES ---\n")
    else:
        prompt_parts.append("\n\n(No key page images selected or provided.)\n")
            
    print(f"Sending {len(prompt_parts)} parts ({len(key_page_images)} images, text length: {len(full_pdf_text)}) to Gemini multimodal model.")

    try:
        # Use the multimodal_eval_model (e.g., gemini-1.5-flash-latest)
        response = multimodal_eval_model.generate_content(prompt_parts)
        return response.text
    except Exception as e:
        print(f"CRITICAL Error during Gemini Hybrid API call: {e}")
        error_response_text = f"Critical Error: Gemini hybrid evaluation API call failed: {str(e)}. Scores will be 0."
        return f"{error_response_text}\n\n**Summary of Scores:**\n\n(No scores due to API error)"

# --- MODIFIED: `run_full_evaluation` to use Hybrid Approach ---
def run_full_evaluation(pdf_path, architect_name, rubric_prompt_text,
                        internal_rubric_keys_list, category_to_key_mapping,
                        num_key_images=10): # Added num_key_images
    """
    Orchestrates the full HYBRID evaluation process.
    """
    print(f"Running HYBRID evaluation for PDF: '{pdf_path}', Architect: '{architect_name}'")

    # 1. Extract full text
    full_text = extract_full_text_from_pdf(pdf_path)

    # 2. Select key page images
    selected_images = select_key_page_images(pdf_path, num_images_to_select=num_key_images)

    # 3. Call Gemini with hybrid inputs
    gemini_raw_response = gemini_evaluate_assignment_hybrid(
        full_pdf_text=full_text,
        key_page_images=selected_images,
        architect_name=architect_name,
        rubric_prompt_template_text=rubric_prompt_text,
        num_selected_images=len(selected_images)
    )
    
    if not gemini_raw_response:
        gemini_raw_response = "Error: Received an empty response from the hybrid evaluation function."
        print(gemini_raw_response)

    # 4. Parse scores (this part remains the same)
    parsed_scores, textual_evaluation = parse_scores_from_markdown_table(
        gemini_raw_response, category_to_key_mapping, internal_rubric_keys_list
    )

    # 5. Calculate final grade (remains the same)
    total_score = sum(parsed_scores.values())
    max_possible_score = len(internal_rubric_keys_list) * 5
    final_percentage = round((total_score / max_possible_score) * 100, 2) if max_possible_score > 0 else 0.0
    grade_map = [
        (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
        (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"), (63, "D"),
        (60, "D-")
    ]
    grade = "F"
    for threshold, letter_grade in grade_map:
        if final_percentage >= threshold:
            grade = letter_grade
            break
    
    print(f"Hybrid Evaluation Complete. Final Score: {total_score}/{max_possible_score} ({final_percentage}%) -> Grade: {grade}")

    return {
        "rubric_scores": parsed_scores,
        "final_percent": final_percentage,
        "grade": grade,
        "detailed_evaluation_text": textual_evaluation,
        "raw_gemini_response": gemini_raw_response,
        "full_extracted_text_snippet": full_text[:1000] + "..." if full_text else "N/A", # For debug
        "num_key_images_processed": len(selected_images) # For debug
    }

def generate_student_facing_feedback(student_name, student_pid, architect_name, evaluation_results_dict):
    # This function's logic remains largely the same, it uses the detailed_evaluation_text
    prompt_for_summary = f"""
    A student, {student_name} (PID: {student_pid}), submitted an assignment about the architect {architect_name}.
    The student's work received a final grade of {evaluation_results_dict['grade']} ({evaluation_results_dict['final_percent']}%).
    The detailed AI-generated evaluation comments (based on full text and key images) are as follows:
    ---
    {evaluation_results_dict['detailed_evaluation_text']}
    ---
    Based *only* on the AI's detailed comments provided above, write a concise summary feedback...
    (Rest of prompt is the same as before)
    """
    try:
        print("Generating student-facing summary feedback...")
        response = text_model.generate_content(prompt_for_summary)
        return response.text
    except Exception as e:
        print(f"Error generating student-facing summary feedback: {e}")
        return "Could not generate summary."

def generate_explanation_for_score(
    architect_name, criterion_name, score_given,
    feedback_text_for_criterion, original_rubric_prompt_text,
    # Potentially add full_text_context and key_image_descriptions_context if needed
    student_submission_context=""):
    # This function's logic also remains largely the same.
    # The original_rubric_prompt_text IS NOW THE HYBRID RUBRIC.
    print(f"Generating explanation for criterion: '{criterion_name}', score: {score_given}/5 (Hybrid context)")
    explanation_prompt = f"""
    You are an AI assistant helping an instructor understand an automated grading process.
    A student's assignment about architect '{architect_name}' was evaluated using a HYBRID approach (full text analysis + key page image analysis).
    The AI used the following original rubric prompt for its evaluation:
    --- START OF ORIGINAL HYBRID RUBRIC PROMPT ---
    {original_rubric_prompt_text}
    --- END OF ORIGINAL HYBRID RUBRIC PROMPT ---

    For criterion: "{criterion_name}", the AI's assessment was:
    - Score: {score_given}/5
    - Detailed Feedback for this criterion: "{feedback_text_for_criterion}"

    (Student submission context: {student_submission_context if student_submission_context else "Based on overall document."})

    Explain the reasoning for this score ({score_given}/5) for "{criterion_name}".
    Consider how the AI was instructed to use both full text and key images for different aspects.
    1. How does the score/feedback align with the rubric for "{criterion_name}"?
    2. What specific elements (textual or visual from key images) likely led to this?
    3. What improvements would lead to a higher score for this criterion, based on the rubric?
    Focus on explaining the existing score. Do not re-grade.
    """
    try:
        response = text_model.generate_content(explanation_prompt)
        return response.text
    except Exception as e:
        print(f"Error generating explanation: {e}")
        return f"Could not generate explanation: {str(e)}"

if __name__ == "__main__":
    print("Testing autograder_logic_v2.py (HYBRID Approach)...")
    test_pdf_path = "/Users/tanishqsingh/Desktop/XR_Lab/autograder_v2/COGS 160_ A1.pdf"
    # IMPORTANT: Ensure this points to your NEW HYBRID RUBRIC PROMPT FILE
    rubric_file_path = os.path.join(os.path.dirname(__file__), 'rubric_prompts', 'current_rubric_hybrid.txt')

    if not os.path.exists(test_pdf_path):
        print(f"FATAL: Test PDF not found: '{test_pdf_path}'")
    elif not os.path.exists(rubric_file_path):
        print(f"FATAL: HYBRID Rubric prompt file not found: '{rubric_file_path}'")
    else:
        try:
            current_hybrid_rubric_text = load_rubric_prompt_from_file(rubric_file_path)
            print(f"Loaded HYBRID rubric: {rubric_file_path}")
            test_architect = "Kazuyo Sejima"
            
            results = run_full_evaluation(
                pdf_path=test_pdf_path,
                architect_name=test_architect,
                rubric_prompt_text=current_hybrid_rubric_text,
                internal_rubric_keys_list=DEFAULT_INTERNAL_RUBRIC_KEYS,
                category_to_key_mapping=CATEGORY_TO_INTERNAL_KEY_MAP,
                num_key_images=10 # How many key images to select
            )
            
            print("\n--- HYBRID Evaluation Results ---")
            print(f"Grade: {results['grade']}, Score: {results['final_percent']}%")
            print(f"Num Key Images Processed: {results['num_key_images_processed']}")
            # print(f"Full Extracted Text Snippet: {results['full_extracted_text_snippet']}")
            print("\nRubric Scores:")
            for key, score in results['rubric_scores'].items():
                print(f"  '{key}': {score}/5")
            
            # ... (rest of the test output for summary and explanation can remain similar) ...

        except Exception as e:
            print(f"Error during HYBRID test run: {e}")
            import traceback
            traceback.print_exc()