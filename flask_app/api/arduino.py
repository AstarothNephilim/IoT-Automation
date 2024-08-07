from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from datetime import datetime, timedelta
import pytz
import os
from ..models import Empresa, Controlador, Signal, User, Aviso, SensorMetrics, db
from flask_login import login_required, current_user
import json

arduino = Blueprint('arduino', __name__)

# Function to load configuration from JSON file
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config_controlador.json')
    with open(config_path, 'r') as config_file:
        config_data = json.load(config_file)
    return config_data

# Load the configuration once at the start
CONFIG_DATA = load_config()

@arduino.route('/test', methods=['GET'])
def test():
    controladores = Controlador.query.all()
    for controlador in controladores:
        print(f"Controlador: {controlador.id}")
        print(f"  - Conectado: {is_controlador_connected(controlador)}")
    
    return jsonify("OK"), 200

@arduino.route('/data', methods=['POST'])
def receive_data():
    try:
        raw_data = request.data.decode('utf-8')
        unique_id, location, tiempo, sensor_states = parse_sensor_states(raw_data)

        print(f"Datos recibidos: {unique_id}, {location}, {tiempo}, {sensor_states}")

        with db.session.begin():
            controlador = get_or_create_controlador(unique_id)
            
            last_signal = Signal.query.filter_by(id=controlador.id).order_by(Signal.tstamp.desc()).first()
            if controlador.config is None:
                controlador.config = CONFIG_DATA
            
            config = controlador.config
            key_to_tipo = {key: value['tipo'] for key, value in config.items()}
            
            sensor_data = add_sensor_data(controlador, sensor_states)
            update_sensor_metrics(controlador, sensor_data, last_signal, key_to_tipo)
            
            db.session.add(sensor_data)
            db.session.commit()

        return jsonify({'message': 'Datos recibidos correctamente'}), 200
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f"Error al procesar los datos: {e}"}), 500

def is_sensor_connected(tipo, sensor_reading):
    if tipo == "NA":
        return not sensor_reading
    if tipo == "NC":
        return sensor_reading
    return False

def is_controlador_connected(controlador):
    last_sample = Signal.query.filter_by(id=controlador.id).order_by(Signal.tstamp.desc()).first()
    if last_sample:
        return last_sample.tstamp > datetime.now(pytz.timezone('Europe/Paris')) - timedelta(minutes=5)
    return False

def parse_sensor_states(raw_data):
    parts = raw_data.split(',')
    if len(parts) != 9:
        raise ValueError("Formato de datos invalido")

    unique_id, location, tiempo, *sensor_states = parts
    sensor_states = [state == '1' for state in sensor_states]
    return unique_id, location, tiempo, sensor_states

def get_or_create_controlador(unique_id):
    print("Hola")
    controlador = Controlador.query.filter_by(id=unique_id).first()
    print(controlador)
    if not controlador:
        raise ValueError("Controlador no registrado")
    return controlador

def add_sensor_data(controlador, sensor_states):
    sensor_data = Signal(
        tstamp=datetime.now(),
        id=controlador.id,
        value_sensor1=sensor_states[0],
        value_sensor2=sensor_states[1],
        value_sensor3=sensor_states[2],
        value_sensor4=sensor_states[3],
        value_sensor5=sensor_states[4],
        value_sensor6=sensor_states[5]
    )
    return sensor_data

def update_sensor_metrics(controlador, sensor_data, last_signal, key_to_tipo):
    sensor_metrics = SensorMetrics.query.filter_by(controlador_id=controlador.id).first()
    if not sensor_metrics:
        sensor_metrics = SensorMetrics(controlador_id=controlador.id)
        db.session.add(sensor_metrics)

    for key, tipo in key_to_tipo.items():
        value = getattr(sensor_data, key)
        sensor_connected = is_sensor_connected(tipo, value)
        if sensor_connected and last_signal:
            current_time = sensor_data.tstamp.replace(tzinfo=last_signal.tstamp.tzinfo)
            if (current_time - last_signal.tstamp) < timedelta(minutes=5):
                time_difference_minutes = (current_time - last_signal.tstamp).total_seconds() / 60
                sensor_time = getattr(sensor_metrics, f'time_{key}') + time_difference_minutes
                setattr(sensor_metrics, f'time_{key}', sensor_time)
    return sensor_metrics
