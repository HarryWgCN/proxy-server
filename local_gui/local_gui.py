import sys
import os
import time
import traceback
from PyQt5.QtWidgets import QDialog, QApplication, QMessageBox, QTextBrowser, QLabel, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QLineEdit
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtNetwork import *
from PyQt5.QtWebSockets import *

disconnect_set = 0

def main():
    app = QApplication(sys.argv)
    w = Window_widget()
    w.resize(500, 300)
    w.move(300, 300)
    w.show()
    print("local_gui on work")
    sys.exit(app.exec_())

class Window_widget(QDialog):   
    def __init__(self):
        super(Window_widget, self).__init__()

        self.setWindowTitle('local_porxy connecter')
        
        #text and input_block each pair is horizon_layout
        self.h_layout1 = QHBoxLayout()
        self.label = QLabel('Local_proxy IP Address ', self)
        self.lineEdit_ip = QLineEdit()
        self.h_layout1.addWidget(self.label)
        self.h_layout1.addWidget(self.lineEdit_ip)
        self.h_layout2 = QHBoxLayout()
        self.label = QLabel('Local_proxy Port       ', self)
        self.lineEdit_port = QLineEdit()
        self.h_layout2.addWidget(self.label)
        self.h_layout2.addWidget(self.lineEdit_port)
        self.h_layout3 = QHBoxLayout()
        self.label = QLabel('Remote_proxy IP Address', self)
        self.lineEdit_rip = QLineEdit()
        self.h_layout3.addWidget(self.label)
        self.h_layout3.addWidget(self.lineEdit_rip)
        self.h_layout4 = QHBoxLayout()
        self.label = QLabel('Remote_proxy Port      ', self)
        self.lineEdit_rport = QLineEdit()
        self.h_layout4.addWidget(self.label)
        self.h_layout4.addWidget(self.lineEdit_rport)
        self.h_layout5 = QHBoxLayout()
        self.label = QLabel('USERNAME  ', self)
        self.lineEdit_user = QLineEdit()
        self.h_layout5.addWidget(self.label)
        self.h_layout5.addWidget(self.lineEdit_user)
        self.h_layout6 = QHBoxLayout()
        self.label = QLabel('PASSWORD  ', self)
        self.lineEdit_pass = QLineEdit()
        self.lineEdit_pass.setEchoMode(QLineEdit.Password)#for safety
        self.h_layout6.addWidget(self.label)
        self.h_layout6.addWidget(self.lineEdit_pass)

        #pairs, two buttons and two text_browsers are vertical_layout
        self.mainLayout = QVBoxLayout()
        self.mainLayout.addLayout(self.h_layout1)
        self.mainLayout.addLayout(self.h_layout2)
        self.mainLayout.addLayout(self.h_layout3)
        self.mainLayout.addLayout(self.h_layout4)
        self.mainLayout.addLayout(self.h_layout5)
        self.mainLayout.addLayout(self.h_layout6)
        self.button1 = QPushButton('connect')
        self.mainLayout.addWidget(self.button1)
        self.button1.clicked.connect(self.connectionStarted)
        self.button2 = QPushButton('disconnect')
        self.mainLayout.addWidget(self.button2)
        self.button2.clicked.connect(self.websocketDisconnected)

        self.label = QLabel('download bandwith', self)
        self.mainLayout.addWidget(self.label)
        self.text_down_load = QTextBrowser()
        self.mainLayout.addWidget(self.text_down_load)
        self.label = QLabel('upload bandwith', self)
        self.mainLayout.addWidget(self.label)
        self.text_up_load = QTextBrowser()
        self.mainLayout.addWidget(self.text_up_load)
        self.setLayout(self.mainLayout)

        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        #self.process.finished.connect(self.processFinished)
        self.process.started.connect(self.processStarted)
        self.process.readyReadStandardOutput.connect(self.processReadyRead)
        self.pythonExec = os.path.basename(sys.executable)


    def processReadyRead(self):
        data = self.process.readAll()
        try:
            msg = data.data().decode().strip()
            print(f'msg={msg}')
        except Exception as exc:
            print(f'{traceback.format_exc()}')
            exit(1)

    def processStarted(self):
        process = self.sender()

    def connectionStarted(self):
        #start local_proxy process
        cmdLine = f"{self.pythonExec} local_proxy.py -d 3 --lh 127.0.0.1 --lp 8888 --rh {self.lineEdit_rip.text()} --rp {self.lineEdit_rport.text()} --ca {self.lineEdit_ip.text()} --cp {self.lineEdit_port.text()}"
        self.process.start(cmdLine)

        time.sleep(3)
        
        alert = QMessageBox()
        alert.setText('You are connecting to local_proxy!')
        alert.exec_()
        self.websocket = QWebSocket()
        self.websocket.connected.connect(self.websocketConnected)
        self.websocket.disconnected.connect(self.websocketDisconnected)
        self.websocket.textMessageReceived.connect(self.websocketMsgRcvd)
        #connect to local_proxy
        uri = "ws://" + self.lineEdit_ip.text() + ":" + self.lineEdit_port.text()
        self.websocket.open(QUrl(uri))

    def websocketMsgRcvd(self, msg):
        global disconnect_set
        if(msg == "check"):#for checking the disconnect command
            if(disconnect_set == 1):
                self.websocket.sendTextMessage("disconnect")
            else:
                self.websocket.sendTextMessage("deliverring message")
        else:
            #show the load information received from local_proxy
            self.text_up_load.clear()
            self.text_down_load.clear()
            msg_list = msg.split(" ")
            self.text_down_load.setText(msg_list[1])
            self.text_up_load.setText(msg_list[2])
            self.websocket.sendTextMessage("deliverring message")
        
    def websocketConnected(self):
        #pass remote_host, remote_port, username and password information
        st = self.lineEdit_rip.text() + " " + self.lineEdit_rport.text() +  " "  + self.lineEdit_user.text() + " " + self.lineEdit_pass.text()
        self.websocket.sendTextMessage(st)

    def websocketDisconnected(self):
        global disconnect_set
        alert = QMessageBox()
        alert.setText('You are disconnecting!')
        alert.exec_()
        #send disconnect command( executed by websocketMsgRcvd as above )
        disconnect_set = 1
        time.sleep(2)
        self.process.kill()

    def websocketDisconnected(self):
        self.process.kill()


if __name__ == '__main__':
    main()


