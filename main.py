# -*- coding: UTF-8 -*-

import argparse
import sys
import time

import cv2
import numpy as np
import PIL.Image
from PIL.ImageOps import pad
from PIL import Image

from pygame import mixer

from covpass_scanner import CovpassScanner
from id_card_scanner import IdCardScanner

DEFAULT_CERTIFICATE_DB_JSON = 'certs/Digital_Green_Certificate_Signing_Keys.json'

CAMERA_ID = 2
CAM_WIDTH, CAM_HEIGHT = 1280, 720

TIME_WAIT_AFTER_CERTIFICATE_FOUND_SEC = 3
TIME_WAIT_FOR_ID_CARD_SEC = 30
TIME_WAIT_BETWEEN_SCANS_SEC = 0.100

TIME_SHOW_INVALID_CERTIFICATE_MESSAGE_SEC = 10
TIME_SHOW_SUCCESSFUL_VERIFICATION_MESSAGE_SEC = 3

BORDER_PERCENTAGE = 0.15
TEXT_COLOR = (255, 255, 255)
SUBTEXT_COLOR = (0, 0, 0)
BORDER_COLOR = (0, 0, 0)
PREVIEW_BORDER_COLOR = (120, 120, 120)

FONT_SIZE = 90

OUTPUT_DISPLAY_RESOLUTION = (1024, 600)

STEP_1_TEXT = 'Step 1: Scan COVPASS Certificate:'
STEP_2_TEXT = 'Step 2: Scan ID card:'


class Main:

    active_certificate_data = None
    last_certificate_found_timestamp = 0
    id_card_matches_certificate = False
    invalid_certificate_found = False

    def __init__(self):
        parser = argparse.ArgumentParser(description='EU COVID Vaccination Passport Verifier')
        # parser.add_argument('--image-file', metavar="IMAGE-FILE",
        #                     help='Image to read QR-code from')
        # parser.add_argument('--raw-string', metavar="RAW-STRING",
        #                     help='Contents of the QR-code as string')
        # parser.add_argument('image_file_positional', metavar="IMAGE-FILE", nargs="?",
        #                     help='Image to read QR-code from')
        parser.add_argument('--certificate-db-json-file', default=DEFAULT_CERTIFICATE_DB_JSON,
                            help="Default: {0}".format(DEFAULT_CERTIFICATE_DB_JSON))
        parser.add_argument('--camera', metavar="CAMERA-FILE",
                            help='camera path')
        parser.add_argument('--id-verification', action='store_true',
                            help='Verify vaccination certificate with personal ID')
        
        args = parser.parse_args()
        self.id_verification = args.id_verification
        if args.camera:
            self.camera_device = args.camera
        else:
            self.camera_device = CAMERA_ID
        #
        # covid_cert_data = None
        # image_file = None
        # if args.image_file_positional:
        #     image_file = args.image_file_positional
        # elif args.image_file:
        #     image_file = args.image_file
        #
        # if image_file:
        #     data = pyzbar.pyzbar.decode(PIL.Image.open(image_file))
        #     covid_cert_data = data[0].data.decode()
        # elif args.raw_string:
        #     covid_cert_data = args.raw_string
        # elif args.camera:
        #     run_interactive(args.camera, args.certificate_db_json_file)
        #     sys.exit(0)
        # else:
        #     log.error("Input parameters: Need either --camera, --image-file or --raw-string QR-code content.")
        #     exit(2)
        #
        # # Got the data, output
        # log.debug("Cert data: '{0}'".format(covid_cert_data))
        # output_covid_cert_data(covid_cert_data, args.certificate_db_json_file)

        self.capture = cv2.VideoCapture(self.camera_device)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)

        self.covpass_scanner = CovpassScanner()
        self.id_card_scanner = IdCardScanner()

        cv2.namedWindow("Camera", cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty("Camera", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        self.font_title = PIL.ImageFont.truetype("fonts/Roboto-Regular.ttf", FONT_SIZE)
        self.font_subtitle = PIL.ImageFont.truetype("fonts/Roboto-Regular.ttf", FONT_SIZE)

        self.__prepare_images()
        self.run_interactive()

    def __prepare_images(self):
        short_side = min(CAM_HEIGHT, CAM_WIDTH)
        self.invalid_certificate_image = cv2.imread("img/failure.png")
        self.invalid_certificate_image = cv2.resize(self.invalid_certificate_image, (short_side, short_side))
        self.invalid_certificate_image = cv2.copyMakeBorder(self.invalid_certificate_image, 0, 0, int((CAM_WIDTH - CAM_HEIGHT) / 2), int((CAM_WIDTH - CAM_HEIGHT) / 2), cv2.BORDER_CONSTANT, value=(255, 255, 255))

        self.successful_verification_image = cv2.imread("img/success.png")
        self.successful_verification_image = cv2.resize(self.successful_verification_image, (short_side, short_side))
        self.successful_verification_image = cv2.copyMakeBorder(self.successful_verification_image, 0, 0, int((CAM_WIDTH - CAM_HEIGHT) / 2), int((CAM_WIDTH - CAM_HEIGHT) / 2), cv2.BORDER_CONSTANT, value=(255, 255, 255))

    def run_interactive(self):
        previous_scan_timestamp = 0
        while True:
            ret, frame = self.capture.read()
            if frame is None:
                print('No frame from camera')
                continue

            frame = cv2.flip(frame, -1)

            now = time.time()

            # Check if a certificate is found in the frame
            found_certificate, is_valid, parsed_covid_cert_data = None, None, None
            if previous_scan_timestamp + TIME_WAIT_BETWEEN_SCANS_SEC < now:
                found_certificate, is_valid, parsed_covid_cert_data = self.covpass_scanner.process_frame(frame)
                previous_scan_timestamp = time.time()

            if found_certificate:
                already_scanned_certificate = self.active_certificate_data == parsed_covid_cert_data
                if not already_scanned_certificate:  # Only continue if it is new certificate
                    if is_valid:
                        # print(parsed_covid_cert_data)
                        # self.on_valid_certificate()
                        self.active_certificate_data = parsed_covid_cert_data
                        self.last_certificate_found_timestamp = now
                        
                    else:
                        self.invalid_certificate_found = True

            elif self.id_verification:  # Only check for ID card if no certificate is found in the current frame
                if self.active_certificate_data is not None:

                    # Wait at least XX seconds after certificate has been detected in frame
                    # This should at least somewhat prevent detecting text from the certificate itself while we have no
                    # proper verification of an ID card
                    if now - self.last_certificate_found_timestamp >= TIME_WAIT_AFTER_CERTIFICATE_FOUND_SEC:
                        self.id_card_matches_certificate = self.id_card_scanner.scan_for_id_cards(frame, self.active_certificate_data)

                    # Delete saved certificate data after XX seconds
                    if now - self.last_certificate_found_timestamp > TIME_WAIT_AFTER_CERTIFICATE_FOUND_SEC + TIME_WAIT_FOR_ID_CARD_SEC:
                        self.active_certificate_data = None

            self.update_ui(frame)

            if self.invalid_certificate_found:
                self.on_invalid_certificate()
                key = cv2.waitKey(TIME_SHOW_INVALID_CERTIFICATE_MESSAGE_SEC * 1000)  # sec to ms
            elif self.active_certificate_data and not self.id_verification:
                self.on_successful_verification()
                key = cv2.waitKey(TIME_SHOW_SUCCESSFUL_VERIFICATION_MESSAGE_SEC * 1000)  # sec to ms
            elif self.id_card_matches_certificate:
                self.on_successful_verification()
                key = cv2.waitKey(TIME_SHOW_SUCCESSFUL_VERIFICATION_MESSAGE_SEC * 1000)  # sec to ms
            else:
                key = cv2.waitKey(1)

            # Press esc or 'q' to close the image window
            if key & 0xFF == ord('q') or key == 27:
                cv2.destroyAllWindows()
                sys.exit(0)

    def update_ui(self, frame):
        # old_shape = frame.shape  # Remember to resize later after adding borders to the frame
        if self.active_certificate_data and not self.id_verification:
            frame = self.successful_verification_image
        elif self.id_card_matches_certificate:
            frame = self.successful_verification_image
        elif self.invalid_certificate_found:
            frame = self.invalid_certificate_image

        frame = self.add_borders_to_frame(frame)
        frame = self.add_text_to_frame(frame)
        # frame = cv2.resize(frame, (old_shape[1], old_shape[0]))
        frame = cv2.resize(frame, OUTPUT_DISPLAY_RESOLUTION)
        cv2.imshow("Camera", frame)

    def add_borders_to_frame(self, frame):
        # Add small black border around camera preview
        frame = cv2.copyMakeBorder(frame, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=PREVIEW_BORDER_COLOR)
        # Add large white border
        frame = cv2.copyMakeBorder(frame,
                                   2 * int(BORDER_PERCENTAGE * frame.shape[0]), 0,
                                   int(BORDER_PERCENTAGE * frame.shape[1]), int(BORDER_PERCENTAGE * frame.shape[1]),
                                   cv2.BORDER_CONSTANT, value=BORDER_COLOR)

        return frame

    def add_text_to_frame(self, frame):
        title = STEP_1_TEXT
        subtitle = ''

        if self.active_certificate_data:
            if self.id_verification:
                title = STEP_2_TEXT
            last_name = self.active_certificate_data['fn'][1]
            first_name = self.active_certificate_data['gn'][1]
            subtitle = 'Name: {} {}'.format(first_name, last_name)

        pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = PIL.ImageDraw.Draw(pil_image)
        title_width = max(draw.textsize(title, font=self.font_title), draw.textsize(title, font=self.font_title))[0]
        title_height = max(draw.textsize(title, font=self.font_title), draw.textsize(title, font=self.font_title))[1]
        subtitle_width = max(draw.textsize(title, font=self.font_subtitle), draw.textsize(title, font=self.font_subtitle))[0]
        # TODO: make drawing code independent of screen size
        title_x = (int((frame.shape[1] - title_width) / 2))
        title_y = int((BORDER_PERCENTAGE * frame.shape[0] - title_height) / 2)
        subtitle_x = int((frame.shape[1] - subtitle_width))
        subtitle_y = frame.shape[0] - 100
        draw.text(xy=(title_x, title_y), text=title, fill=TEXT_COLOR, font=self.font_title)
        draw.text(xy=(subtitle_x, subtitle_y), text=subtitle, fill=SUBTEXT_COLOR, font=self.font_subtitle)

        frame[:] = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

        return frame

    def reset(self):
        self.active_certificate_data = None
        self.last_certificate_found_timestamp = 0
        self.id_card_matches_certificate = False
        self.invalid_certificate_found = False

        # Hotfix hack
        # without multithreading, the code will block and use buffered frames from several seconds ago
        # when image analysis finishes.
        # this results in analysing phantom barcodes, that are no longer physically present
        # restarting the camera clears the buffer.
        # TODO: implement this properly
        self.capture.release()
        self.capture = cv2.VideoCapture(self.camera_device)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)

    def on_successful_verification(self):
        mixer.init()
        mixer.music.load("sounds/complete.oga")
        mixer.music.play()

        self.reset()

    def on_valid_certificate(self):
        mixer.init()
        mixer.music.load("sounds/message.oga")
        mixer.music.play()

    def on_invalid_certificate(self):
        mixer.init()
        mixer.music.load("sounds/dialog-error.oga")
        mixer.music.play()

        self.reset()


def main():
    Main()
    sys.exit()


if __name__ == '__main__':
    main()
