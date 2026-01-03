from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import fitz  # PyMuPDF
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'tmp/uploads'
EDITED_FOLDER = 'tmp/edited'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EDITED_FOLDER, exist_ok=True)

# Store sessions
sessions = {}

@app.route('/api/upload', methods=['POST'])
def upload_pdf():
    """Upload PDF and extract text data"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '' or not file.filename.endswith('.pdf'):
        return jsonify({'error': 'Invalid file'}), 400
    
    try:
        session_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, f"{session_id}_{filename}")
        file.save(filepath)
        
        # Open PDF and extract text data
        pdf_doc = fitz.open(filepath)
        page = pdf_doc[0]
        
        # Extract text with positions
        text_data = []
        text_dict = page.get_text("dict")
        
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text_data.append({
                            'bbox': span["bbox"],
                            'text': span["text"],
                            'font': span["font"],
                            'size': span["size"],
                            'color': span["color"],
                            'flags': span["flags"]
                        })
        
        pdf_doc.close()
        
        sessions[session_id] = {
            'filepath': filepath,
            'filename': filename,
            'changes': []
        }
        
        return jsonify({
            'session_id': session_id,
            'filename': filename,
            'text_data': text_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/pdf/<session_id>', methods=['GET'])
def get_pdf(session_id):
    """Get the PDF file"""
    if session_id not in sessions:
        return jsonify({'error': 'Invalid session'}), 404
    
    filepath = sessions[session_id]['filepath']
    return send_file(filepath, mimetype='application/pdf')

@app.route('/api/edit/<session_id>', methods=['POST'])
def save_edit(session_id):
    """Save text edit"""
    if session_id not in sessions:
        return jsonify({'error': 'Invalid session'}), 404
    
    data = request.json
    bbox = data.get('bbox')
    new_text = data.get('new_text')
    original_data = data.get('original')
    
    session = sessions[session_id]
    
    change = {
        'bbox': bbox,
        'old_text': original_data.get('text', ''),
        'new_text': new_text,
        'font': original_data.get('font', ''),
        'size': original_data.get('size', 12),
        'color': original_data.get('color', 0),
        'flags': original_data.get('flags', 0)
    }
    
    session['changes'] = [c for c in session['changes'] if c['bbox'] != bbox]
    session['changes'].append(change)
    
    return jsonify({
        'success': True,
        'changes_count': len(session['changes'])
    })

@app.route('/api/save/<session_id>', methods=['POST'])
def save_pdf(session_id):
    """Save edited PDF"""
    if session_id not in sessions:
        return jsonify({'error': 'Invalid session'}), 404
    
    session = sessions[session_id]
    
    if not session['changes']:
        return jsonify({'error': 'No changes'}), 400
    
    try:
        output = fitz.open(session['filepath'])
        page = output[0]
        
        # Remove old text
        for change in session['changes']:
            rect = fitz.Rect(change['bbox'])
            rect.x0 -= 1
            rect.y0 -= 1
            rect.x1 += 1
            rect.y1 += 1
            page.add_redact_annot(rect, fill=(1, 1, 1))
        
        page.apply_redactions()
        
        # Add new text
        for change in session['changes']:
            fname = change['font'].lower()
            
            if 'helv' in fname or 'arial' in fname or 'sans' in fname:
                base = 'helv'
            elif 'times' in fname or 'roman' in fname:
                base = 'times-roman'
            elif 'cour' in fname or 'mono' in fname:
                base = 'cour'
            else:
                base = 'helv'
            
            bold = bool(change['flags'] & 16)
            italic = bool(change['flags'] & 2)
            
            if base == 'helv':
                font = 'helv-boldoblique' if bold and italic else 'helv-bold' if bold else 'helv-oblique' if italic else 'helv'
            elif base == 'times-roman':
                font = 'times-bolditalic' if bold and italic else 'times-bold' if bold else 'times-italic' if italic else 'times-roman'
            else:
                font = 'cour-boldoblique' if bold and italic else 'cour-bold' if bold else 'cour-oblique' if italic else 'cour'
            
            c = change['color']
            rgb = (((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0)
            
            try:
                page.insert_text(
                    fitz.Point(change['bbox'][0], change['bbox'][3]),
                    change['new_text'],
                    fontsize=change['size'],
                    fontname=font,
                    color=rgb
                )
            except:
                page.insert_text(
                    fitz.Point(change['bbox'][0], change['bbox'][3]),
                    change['new_text'],
                    fontsize=change['size'],
                    fontname='helv'
                )
        
        output_filename = f"edited_{session['filename']}"
        output_path = os.path.join(EDITED_FOLDER, f"{session_id}_{output_filename}")
        output.save(output_path, garbage=4, deflate=True, clean=True)
        output.close()
        
        return send_file(output_path, as_attachment=True, download_name=output_filename)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)