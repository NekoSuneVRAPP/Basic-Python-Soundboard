import sys
import os
import pyaudio
import wave
import psutil
import random
import string
import json
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QKeySequence, QKeyEvent
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QComboBox, QLabel, QVBoxLayout, QWidget, 
    QTableWidget, QTableWidgetItem, QAbstractItemView, QFileDialog, QInputDialog, QMessageBox,
    QShortcut
)
import threading
import winsound

from pydub import AudioSegment
from pydub.playback import play

def generate_unique_filename(extension=".wav"):
    """ Generate a unique filename using a random string. """
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10)) + extension

def save_soundboard_data(file_path, data):
    """ Save the soundboard data to a JSON file. """
    with open(file_path, 'w') as f:
        json.dump(data, f)

def load_soundboard_data(file_path):
    """ Load the soundboard data from a JSON file. """
    if os.path.isfile(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return []

class AudioRecorder(QThread):
    update_status = pyqtSignal(str)
    file_name = ""

    def __init__(self, device_index, output_folder, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.output_folder = output_folder
        self.running = False

    def run(self):
        FORMAT = pyaudio.paInt16
        CHANNELS = 2
        SAMPLE_RATE = 44100
        CHUNK = 1024
        self.p = pyaudio.PyAudio()

        try:
            self.stream = self.p.open(format=FORMAT,
                                      channels=CHANNELS,
                                      rate=SAMPLE_RATE,
                                      input=True,
                                      input_device_index=self.device_index,
                                      frames_per_buffer=CHUNK)
        except IOError as e:
            self.update_status.emit(f"Failed to open stream: {e}")
            self.p.terminate()
            return
        except Exception as e:
            self.update_status.emit(f"An unexpected error occurred: {e}")
            self.p.terminate()
            return

        frames = []
        self.file_name = os.path.join(self.output_folder, generate_unique_filename())
        self.update_status.emit(f"Recording to {self.file_name}...")
        self.running = True

        while self.running:
            try:
                data = self.stream.read(CHUNK)
                frames.append(data)
            except IOError as e:
                self.update_status.emit(f"Recording error: {e}")
                break

        self.update_status.emit("Stopped")
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()

        with wave.open(self.file_name, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.p.get_sample_size(FORMAT))
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b''.join(frames))

    def stop(self):
        self.running = False

    def playback(self, file_path, device_index=None):
        """ Play back audio using the specified output device index. """
        if os.path.isfile(file_path):
            if device_index is None:
                winsound.PlaySound(file_path, winsound.SND_FILENAME)
            else:
                # Use pyaudio for more control over output devices
                p = pyaudio.PyAudio()
                wf = wave.open(file_path, 'rb')
                stream = p.open(format=pyaudio.paInt16,
                                channels=wf.getnchannels(),
                                rate=wf.getframerate(),
                                output=True,
                                output_device_index=device_index)

                data = wf.readframes(1024)
                while data:
                    stream.write(data)
                    data = wf.readframes(1024)

                stream.stop_stream()
                stream.close()
                p.terminate()

class SoundboardTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(6)  # 6 columns for sound file, hotkey, actions, binding, playback, and output device
        self.setHorizontalHeaderLabels(["Sound", "Hotkey", "Action", "Bind", "Play", "Output Device"])
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setRowCount(0)
        self.hotkeys = {}
        self.file_paths = {}
        self.binding_row = None
        self.bind_checkbox_widgets = {}

        self.output_devices = {}  # Store device indices and names

    def set_output_devices(self, device_list):
        """ Store available output devices and indices. """
        self.output_devices = device_list

    def add_sound(self, file_path, hotkey):
        row_position = self.rowCount()
        self.insertRow(row_position)
        self.setItem(row_position, 0, QTableWidgetItem(os.path.basename(file_path)))
        self.setItem(row_position, 1, QTableWidgetItem(hotkey))
        
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(lambda: self.delete_sound(row_position))
        self.setCellWidget(row_position, 2, delete_button)

        # Add a checkbox for binding
        bind_checkbox = QPushButton("Bind")
        bind_checkbox.setCheckable(True)
        bind_checkbox.clicked.connect(lambda: self.bind_checkbox_clicked(row_position))
        self.setCellWidget(row_position, 3, bind_checkbox)

        # Add a button for playback
        play_button = QPushButton("Play")
        play_button.clicked.connect(lambda: self.play_sound(file_path))
        self.setCellWidget(row_position, 4, play_button)

        # Add dropdown for output device selection
        output_device_combo = QComboBox(self)
        output_device_combo.addItems(self.output_devices.values())
        output_device_combo.currentIndexChanged.connect(lambda: self.set_output_device(row_position, output_device_combo.currentData()))
        self.setCellWidget(row_position, 5, output_device_combo)

    def set_output_device(self, row_position, device_index):
        self.file_paths[row_position] = (self.file_paths.get(row_position, (None, None))[0], device_index)

    def update_hotkeys(self, file_path, hotkey, row_position):
        if hotkey:
            # Remove existing hotkey if re-binding
            existing_file = self.hotkeys.get(hotkey)
            if existing_file:
                self.hotkeys.pop(hotkey)
                self.file_paths.pop(existing_file)
                # Update old row if it's still valid
                for i in range(self.rowCount()):
                    if self.item(i, 0).text() == os.path.basename(existing_file):
                        self.setItem(i, 1, QTableWidgetItem(""))  # Clear old hotkey
                        self.bind_checkbox_widgets[i].setChecked(False)
                        break
        
        self.hotkeys[hotkey] = file_path
        self.file_paths[file_path] = hotkey

    def bind_checkbox_clicked(self, row_position):
        if self.binding_row is not None and self.binding_row != row_position:
            self.bind_checkbox_widgets[self.binding_row].setChecked(False)
        
        self.binding_row = row_position

    def delete_sound(self, row_position):
        file_name = self.item(row_position, 0).text()
        file_path = os.path.join("audio_files", file_name)
        hotkey = self.item(row_position, 1).text()

        reply = QMessageBox.question(self, 'Delete Sound', 
                                     f"Are you sure you want to delete {file_name}?", 
                                     QMessageBox.Yes | QMessageBox.No, 
                                     QMessageBox.No)
        if reply == QMessageBox.Yes:
            if os.path.isfile(file_path):
                os.remove(file_path)

            # Remove from internal data structures
            if hotkey in self.hotkeys:
                del self.hotkeys[hotkey]
            if file_path in self.file_paths:
                del self.file_paths[file_path]

            # Remove row from table
            self.removeRow(row_position)

            # Update JSON file
            self.update_soundboard_data()

    def update_soundboard_data(self):
        # Update the soundboard data
        self.soundboard_data = [{'file': path, 'hotkey': key} for key, path in self.hotkeys.items()]
        save_soundboard_data("soundboard_data.json", self.soundboard_data)

    def play_sound(self, file_path):
        def playback():
            # Find row by file path
            for row in range(self.rowCount()):
                if self.item(row, 0).text() == os.path.basename(file_path):
                    output_device = self.file_paths.get(row, (None, None))[1]
                    break
            else:
                output_device = None  # Default to system default if not found

            if os.path.isfile(file_path):
                recorder = AudioRecorder(0, "audio_files")  # Example of using AudioRecorder
                recorder.playback(file_path, output_device)

        # Run the playback in a separate thread
        playback_thread = threading.Thread(target=playback)
        playback_thread.start()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Game Audio Recorder")
        self.setGeometry(100, 100, 800, 600)

        self.output_folder = "audio_files"
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)

        self.soundboard_data_file = "soundboard_data.json"
        self.soundboard_data = load_soundboard_data(self.soundboard_data_file)

        self.init_ui()
        self.update_device_lists()
        self.load_soundboard()

    def init_ui(self):
        self.status_label = QLabel("Select audio input device", self)

        self.input_device_combo = QComboBox(self)
        self.input_device_combo.currentIndexChanged.connect(self.input_device_changed)

        self.output_device_combo = QComboBox(self)
        self.output_device_combo.currentIndexChanged.connect(self.output_device_changed)

        self.start_button = QPushButton("Start Recording", self)
        self.start_button.clicked.connect(self.start_recording)

        self.stop_button = QPushButton("Stop Recording", self)
        self.stop_button.clicked.connect(self.stop_recording)
        self.stop_button.setEnabled(False)

        self.soundboard_table = SoundboardTable(self)
        self.soundboard_table.setGeometry(50, 50, 700, 300)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("Select Audio Input Device:"))
        layout.addWidget(self.input_device_combo)
        layout.addWidget(QLabel("Select Audio Output Device:"))
        layout.addWidget(self.output_device_combo)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.soundboard_table)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.hotkey_shortcuts = []
        self.current_recorded_file = None

    def update_device_lists(self):
        self.audio_input_devices = []
        self.audio_output_devices = {}
        self.input_device_combo.clear()
        self.output_device_combo.clear()

        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                self.input_device_combo.addItem(device_info['name'], i)
                self.audio_input_devices.append(device_info['name'])
            if device_info['maxOutputChannels'] > 0:
                self.output_device_combo.addItem(device_info['name'], i)
                self.audio_output_devices[i] = device_info['name']  # Store index -> name mapping
        p.terminate()

        # Pass the output devices to the soundboard table
        self.soundboard_table.set_output_devices(self.audio_output_devices)

    def input_device_changed(self):
        self.input_device_index = self.input_device_combo.currentData()

    def output_device_changed(self):
        self.output_device_index = self.output_device_combo.currentData()

    def start_recording(self):
        self.device_index = self.input_device_combo.currentData()
        self.recorder = AudioRecorder(self.device_index, self.output_folder)
        self.recorder.update_status.connect(self.status_label.setText)
        self.recorder.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_recording(self):
        if hasattr(self, 'recorder'):
            self.recorder.stop()
            self.recorder.wait()
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.current_recorded_file = self.recorder.file_name
            self.add_sound_to_board(self.current_recorded_file)

            self.status_label.setText("Press a key to bind the hotkey...")

    def add_sound_to_board(self, file_path):
        self.soundboard_table.add_sound(file_path, "")
        self.soundboard_data.append({'file': file_path, 'hotkey': ""})
        save_soundboard_data(self.soundboard_data_file, self.soundboard_data)

    def keyPressEvent(self, event: QKeyEvent):
        if self.current_recorded_file and self.soundboard_table.binding_row is not None:
            hotkey = QKeySequence(event.key()).toString()
            if hotkey in self.soundboard_table.hotkeys:
                QMessageBox.warning(self, "Hotkey Conflict", f"The hotkey '{hotkey}' is already in use.")
            else:
                row_position = self.soundboard_table.binding_row
                existing_hotkey = self.soundboard_table.item(row_position, 1).text()
                
                if existing_hotkey:
                    self.soundboard_table.hotkeys.pop(existing_hotkey, None)
                    self.soundboard_table.file_paths.pop(self.current_recorded_file, None)
                
                self.soundboard_table.setItem(row_position, 1, QTableWidgetItem(hotkey))
                self.soundboard_table.update_hotkeys(self.current_recorded_file, hotkey, row_position)
                
                for entry in self.soundboard_data:
                    if entry['file'] == self.current_recorded_file:
                        entry['hotkey'] = hotkey
                        break
                save_soundboard_data(self.soundboard_data_file, self.soundboard_data)
                
                self.current_recorded_file = None
                self.soundboard_table.bind_checkbox_widgets[row_position].setChecked(False)
                self.soundboard_table.binding_row = None
                self.status_label.setText("Hotkey bound successfully.")
        else:
            super().keyPressEvent(event)  # Handle other key press events

    def load_soundboard(self):
        for entry in self.soundboard_data:
            file_path = entry['file']
            hotkey = entry['hotkey']
            self.soundboard_table.add_sound(file_path, hotkey)
            if hotkey:
                self.set_hotkey(hotkey, file_path)

    def set_hotkey(self, hotkey, file_path):
        shortcut = QShortcut(QKeySequence(hotkey), self)
        shortcut.setContext(Qt.ApplicationShortcut)  # Make it global
        shortcut.activated.connect(lambda: self.play_sound(file_path))
        self.hotkey_shortcuts.append(shortcut)

    def play_sound(self, file_path):
        if os.path.isfile(file_path):
            output_device = self.output_device_index if hasattr(self, 'output_device_index') else None
            self.recorder.playback(file_path, output_device)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
