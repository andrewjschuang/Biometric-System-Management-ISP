from flask import Flask, request, redirect, url_for, render_template
from base64 import b64encode
import io
import cv2
import json
import time
import datetime
import threading
import numpy as np
from PIL import Image

import config
from recognition.Recognition import Recognition
from entities.Person import Person
from entities.PhotoCategory import PhotoCategory
from entities.Calendar import Calendar
from entities.Sunday import Sunday

ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])

app = Flask(__name__)
recognition = Recognition()

photo_labels = ['central', 'direita', 'esquerda']

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def image_validation(request, filename='file'):
    if type(filename) == list:
        if len(request.files) == 0:
            return {'error': True, 'message': 'no image received'}
        return {'error': False}

    if filename not in request.files:
        return {'error': True, 'message': 'no image received'}

    file = request.files['file']

    if file.filename == '':
        return {'error': True, 'message': 'no selected image'}

    if not (file and allowed_file(file.filename)):
        return {'error': True, 'message': 'file is not an image'}

    return {'error': False}

def get_image(image):
    in_memory_file = io.BytesIO()
    image.save(in_memory_file)
    data = np.fromstring(in_memory_file.getvalue(), dtype=np.uint8)
    color_image_flag = 1
    img = cv2.imdecode(data, color_image_flag)
    return img

def get_person_image_from_bytes(bytes, resize):
    image = Image.open(io.BytesIO(bytes))
    imgByteArr = io.BytesIO()
    new_size = (int(image.size[0]*resize), int(image.size[0]*resize))
    image.thumbnail(new_size, Image.ANTIALIAS)
    image.save(imgByteArr, format='JPEG')
    return b64encode(imgByteArr.getvalue()).decode('utf-8')

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/recognize', methods=['GET', 'POST'])
def recognize():
    if request.method == 'POST':
        result = image_validation(request)

        if result['error']:
            return render_template('error.html', error=result['message'])

        image = get_image(request.files['file'])
        found = recognition.recognize(image)
        names = []

        if found:
            for x in found:
                recognition.db.event_occured(time.time(), x['id'], x['name'])
                names.append(x['name'])

        return render_template('found.html', found=names)

    return render_template('recognize.html')

@app.route('/api', methods=['POST'])
def api():
    result = image_validation(request)

    if result['error']:
        response = {
            'error': result['message']
        }
        return json.dumps(response)

    image = get_image(request.files['file'])
    found = recognition.recognize(image)
    response = {
        'results': found
    }

    return json.dumps(response)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        result = image_validation(request, photo_labels)

        if result['error']:
            return render_template('error.html', error=result['message'])

        member = {key: request.form[key]
                  for key in request.form if request.form[key]}
        member['data_foto'] = datetime.datetime.now().isoformat()
        member['fotos'] = {}
        member['images'] = {}
        member_id = recognition.db.insert('members', member)

        images = request.files
        for image_label in images:
            try:
                image = get_image(images[image_label])
                face_locations, face_encodings = recognition.get_faces_from_picture(
                    image)

                if len(face_encodings) == 0:
                    return render_template('error.html', error='no face found')
                if len(face_encodings) > 1:
                    return render_template('error.html', error='more than one face found')

                encoding = {
                    'nome': member['nome'],
                    'member_id': member_id,
                    'foto': face_encodings[0].tolist(),
                    'obs': None
                }
                encoding_id = recognition.db.insert('encodings', encoding)
                member['fotos'][image_label] = encoding_id

                image = Image.open(images[image_label])
                imgByteArr = io.BytesIO()
                image.save(imgByteArr, format='JPEG')
                image_id = recognition.db.fs.put(imgByteArr.getvalue())
                member['images'][image_label] = image_id
            except Exception as e:
                print('failed to retrieve image: %s' % image_label)

        recognition.db.get_collection('members').replace_one({'_id': member_id}, member)
        recognition.get_known_encodings()

        return render_template('registered.html', name=member['nome'])

    return render_template('register.html', labels=photo_labels)

@app.route('/start', methods=['GET'])
def start():
    if not recognition.run:
        recognition.signal_handler(run=True)
        threading.Thread(target=recognition.start).start()
    return render_template('start.html')

@app.route('/stop', methods=['GET'])
def stop():
    recognition.signal_handler()
    return render_template('stop.html')

@app.route('/management', methods=['GET'])
def management():
    persons = recognition.db.get_all_members()
    for person in persons:
        try:
            image_bytes = recognition.db.get_image(person.encodings[PhotoCategory.FRONT.name])
            person.encodings[PhotoCategory.FRONT.name] = get_person_image_from_bytes(image_bytes, 0.05)
        except Exception as e:
            person.encodings[PhotoCategory.FRONT.name] = b''
    return render_template('management.html', persons=persons)

@app.route('/management/<_id>', methods=['GET', 'POST'])
def get(_id):
    person = recognition.db.get_member_by_id(_id)
    image_bytes = recognition.db.get_image(person.encodings[PhotoCategory.FRONT.name])
    image = get_person_image_from_bytes(image_bytes, 0.15)
    year = str(datetime.datetime.now().year)

    if request.method == 'POST':
        person.calendar.sundays = [Sunday.from_str(key, request.form[key]) for key in request.form]
        recognition.db.update_member_calendar(person)

    return render_template('person.html', person=person, image=image)

@app.route('/configure', methods=['GET'])
def configure():
    video_source = request.args.get('source')
    display_image = request.args.get('display')
    tolerance = request.args.get('tolerance')

    error = recognition.configure(video_source, display_image, tolerance)
    return render_template('updated.html', error=error)

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)

# curl -X GET http://localhost:5000
# curl -F "file=@/home/andrewjschuang/dev/biometric-system-management/photos_for_encoding/random/andrew.jpg" -X POST http://localhost:5000
