import configparser
import inspect
import pathlib
import platform
import subprocess
import time

import stm32pio.lib
import stm32pio.settings
import stm32pio.util

from tests.test import *


class TestUnit(CustomTestCase):
    """
    Test the single method. As we at some point decided to use a class instead of the set of scattered functions we need
    to do some preparations for almost every test (e.g. instantiate the class, create the PlatformIO project, etc.),
    though, so the architecture now is way less modular
    """

    def test_generate_code(self):
        """
        Check whether files and folders have been created (by STM32CubeMX)
        """
        project = stm32pio.lib.Stm32pio(FIXTURE_PATH, parameters={'board': TEST_PROJECT_BOARD},
                                        save_on_destruction=False)
        project.generate_code()

        # Assuming that the presence of these files indicating a success
        files_should_be_present = ['Src/main.c', 'Inc/main.h']
        for file in files_should_be_present:
            with self.subTest(msg=f"{file} hasn't been created"):
                self.assertEqual(FIXTURE_PATH.joinpath(file).is_file(), True)

    def test_pio_init(self):
        """
        Consider that existence of 'platformio.ini' file showing a successful PlatformIO project initialization. The
        last one has another traces that can be checked too but we are interested only in a 'platformio.ini' anyway.
        Also, check that it is a correct configparser file and is not empty
        """
        project = stm32pio.lib.Stm32pio(FIXTURE_PATH, parameters={'board': TEST_PROJECT_BOARD},
                                        save_on_destruction=False)
        result = project.pio_init()

        self.assertEqual(result, 0, msg="Non-zero return code")
        self.assertTrue(FIXTURE_PATH.joinpath('platformio.ini').is_file(), msg="platformio.ini is not there")

        platformio_ini = configparser.ConfigParser(interpolation=None)
        self.assertGreater(len(platformio_ini.read(str(FIXTURE_PATH.joinpath('platformio.ini')))), 0,
                           msg='platformio.ini is empty')

    def test_patch(self):
        """
        Check that new parameters were added, modified were updated and existing parameters didn't gone. Also, check for
        unnecessary folders deletion
        """
        project = stm32pio.lib.Stm32pio(FIXTURE_PATH, save_on_destruction=False)

        test_content = inspect.cleandoc('''
            ; This is a test config .ini file
            ; with a comment. It emulates a real
            ; platformio.ini file

            [platformio]
            include_dir = this s;789hould be replaced
            ; there should appear a new parameter
            test_key3 = this should be preserved

            [test_section]
            test_key1 = test_value1
            test_key2 = 123
        ''') + '\n'
        FIXTURE_PATH.joinpath('platformio.ini').write_text(test_content)
        FIXTURE_PATH.joinpath('include').mkdir()

        project.patch()

        with self.subTest():
            self.assertFalse(FIXTURE_PATH.joinpath('include').is_dir(), msg="'include' has not been deleted")

        original_test_config = configparser.ConfigParser(interpolation=None)
        original_test_config.read_string(test_content)

        patched_config = configparser.ConfigParser(interpolation=None)
        patch_config = configparser.ConfigParser(interpolation=None)
        patch_config.read_string(project.config.get('project', 'platformio_ini_patch_content'))

        self.assertGreater(len(patched_config.read(FIXTURE_PATH.joinpath('platformio.ini'))), 0)

        for patch_section in patch_config.sections():
            self.assertTrue(patched_config.has_section(patch_section), msg=f"{patch_section} is missing")
            for patch_key, patch_value in patch_config.items(patch_section):
                self.assertEqual(patched_config.get(patch_section, patch_key, fallback=None), patch_value,
                                 msg=f"{patch_section}: {patch_key}={patch_value} is missing or incorrect in the "
                                     "patched config")

        for original_section in original_test_config.sections():
            self.assertTrue(patched_config.has_section(original_section),
                            msg=f"{original_section} from the original config is missing")
            for original_key, original_value in original_test_config.items(original_section):
                # We've already checked patch parameters so skip them
                if not patch_config.has_option(original_section, original_key):
                    self.assertEqual(patched_config.get(original_section, original_key), original_value,
                                     msg=f"{original_section}: {original_key}={original_value} is corrupted")

    def test_build_should_handle_error(self):
        """
        Build an empty project so PlatformIO should return an error
        """
        project = stm32pio.lib.Stm32pio(FIXTURE_PATH, parameters={'board': TEST_PROJECT_BOARD},
                                        save_on_destruction=False)
        project.pio_init()

        with self.assertLogs(level='ERROR') as logs:
            self.assertNotEqual(project.build(), 0, msg="Build error was not indicated")
            # next() - Technique to find something in array, string, etc. (or to indicate that there is no)
            self.assertTrue(next((True for item in logs.output if "PlatformIO build error" in item), False),
                            msg="Error message does not match")

    def test_start_editor(self):
        """
        Call the editors
        """
        project = stm32pio.lib.Stm32pio(FIXTURE_PATH, save_on_destruction=False)

        editors = {
            'atom': {
                'Windows': 'atom.exe',
                'Darwin': 'Atom',
                'Linux': 'atom'
            },
            'code': {
                'Windows': 'Code.exe',
                'Darwin': 'Visual Studio Code',
                'Linux': 'code'
            },
            'subl': {
                'Windows': 'sublime_text.exe',
                'Darwin': 'Sublime',
                'Linux': 'sublime'
            }
        }

        for editor, editor_process_names in editors.items():
            # Look for the command presence in the system so we test only installed editors
            if platform.system() == 'Windows':
                command_str = f"where {editor} /q"
            else:
                command_str = f"command -v {editor}"
            editor_exists = False
            if subprocess.run(command_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0:
                editor_exists = True

            if editor_exists:
                with self.subTest(command=editor, name=editor_process_names[platform.system()]):
                    project.start_editor(editor)

                    time.sleep(1)  # wait a little bit for app to start

                    if platform.system() == 'Windows':
                        command_arr = ['wmic', 'process', 'get', 'description']
                    else:
                        command_arr = ['ps', '-A']
                    # "encoding='utf-8'" is for "a bytes-like object is required, not 'str'" in "assertIn"
                    result = subprocess.run(command_arr, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            encoding='utf-8')
                    # Or, for Python 3.7 and above:
                    # result = subprocess.run(command_arr, capture_output=True, encoding='utf-8')
                    self.assertIn(editor_process_names[platform.system()], result.stdout)

    def test_init_path_not_found_should_raise(self):
        """
        Pass non-existing path and expect the error
        """
        path_does_not_exist_name = 'does_not_exist'

        path_does_not_exist = FIXTURE_PATH.joinpath(path_does_not_exist_name)
        with self.assertRaisesRegex(FileNotFoundError, path_does_not_exist_name,
                                    msg="FileNotFoundError was not raised or doesn't contain a description"):
            stm32pio.lib.Stm32pio(path_does_not_exist, save_on_destruction=False)

    def test_save_config(self):
        """
        Explicitly save the config to file and look did that actually happen and whether all the information was
        preserved
        """
        # 'board' is non-default, 'project'-section parameter
        project = stm32pio.lib.Stm32pio(FIXTURE_PATH, parameters={'board': TEST_PROJECT_BOARD},
                                        save_on_destruction=False)
        project.save_config()

        self.assertTrue(FIXTURE_PATH.joinpath(stm32pio.settings.config_file_name).is_file(),
                        msg=f"{stm32pio.settings.config_file_name} file hasn't been created")

        config = configparser.ConfigParser(interpolation=None)
        self.assertGreater(len(config.read(str(FIXTURE_PATH.joinpath(stm32pio.settings.config_file_name)))), 0,
                           msg="Config is empty")
        for section, parameters in stm32pio.settings.config_default.items():
            for option, value in parameters.items():
                with self.subTest(section=section, option=option,
                                  msg="Section/key is not found in the saved config file"):
                    self.assertNotEqual(config.get(section, option, fallback="Not found"), "Not found")

        self.assertEqual(config.get('project', 'board', fallback="Not found"), TEST_PROJECT_BOARD,
                         msg="'board' has not been set")

    def test_get_platformio_boards(self):
        """
        PlatformIO identifiers of boards are requested using PlatformIO CLI in JSON format
        """
        self.assertIsInstance(stm32pio.util.get_platformio_boards(platformio_cmd='platformio'), list)
