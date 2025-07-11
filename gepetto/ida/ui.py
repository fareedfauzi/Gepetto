import functools
import random
import string
import threading

import idaapi
import ida_hexrays
import ida_kernwin

import gepetto.config
from gepetto.ida.handlers import (
    ExplainHandler,
    RenameHandler,
    SwapModelHandler,
    GenerateCCodeHandler,
    GeneratePythonCodeHandler,
    RenameFunctionHandler,
    ExplainMalwareBehaviorHandler,
    RenameMalwareFunctionHandler,  # <- Added
)
from gepetto.ida.cli import register_cli
import gepetto.models.model_manager

_ = gepetto.config._


class GepettoPlugin(idaapi.plugin_t):
    flags = 0

    explain_action_name = "gepetto:explain_function"
    rename_action_name = "gepetto:rename_variables"
    rename_func_action_name = "gepetto:rename_function"
    rename_func_malware_action_name = "gepetto:rename_function_malware"
    explain_malware_action_name = "gepetto:explain_malware_behavior"
    c_code_action_name = "gepetto:generate_c_code"
    python_code_action_name = "gepetto:generate_python_code"

    explain_menu_path = "Edit/Gepetto/" + _("Explain function")
    rename_menu_path = "Edit/Gepetto/" + _("Rename variables")
    rename_func_menu_path = "Edit/Gepetto/" + _("Rename function (code context)")
    rename_func_malware_menu_path = "Edit/Gepetto/" + _("Rename function (malware context)")
    explain_malware_menu_path = "Edit/Gepetto/" + _("Explain malware behavior")
    c_code_menu_path = "Edit/Gepetto/" + _("Generate C Code")
    python_code_menu_path = "Edit/Gepetto/" + _("Generate Python Code")

    wanted_name = 'Gepetto'
    wanted_hotkey = ''
    comment = _("Uses {model} to enrich the decompiler's output").format(model=str(gepetto.config.model))
    help = _("See usage instructions on GitHub")
    menu = None
    model_action_map = {}

    def init(self):
        if not ida_hexrays.init_hexrays_plugin():
            return idaapi.PLUGIN_SKIP
        if not gepetto.config.model:
            return idaapi.PLUGIN_SKIP

        # Register actions
        idaapi.register_action(idaapi.action_desc_t(
            self.explain_action_name,
            _('Explain function'),
            ExplainHandler(),
            "Ctrl+Alt+G",
            _('Use {model} to explain the currently selected function').format(model=str(gepetto.config.model)),
            452))

        idaapi.register_action(idaapi.action_desc_t(
            self.rename_action_name,
            _('Rename variables'),
            RenameHandler(),
            "Ctrl+Alt+R",
            _("Use {model} to rename this function's variables").format(model=str(gepetto.config.model)),
            19))

        idaapi.register_action(idaapi.action_desc_t(
            self.rename_func_action_name,
            _('Rename function (code context)'),
            RenameFunctionHandler(),
            "Ctrl+Alt+N",
            _("Use {model} to rename this function with a 'fn_' prefix").format(model=str(gepetto.config.model)),
            203))

        idaapi.register_action(idaapi.action_desc_t(
            self.rename_func_malware_action_name,
            _('Rename function (malware context)'),
            RenameMalwareFunctionHandler(),
            "Ctrl+Alt+M",
            _("Use {model} to rename this function with a 'fn_' prefix in malware context").format(model=str(gepetto.config.model)),
            204))

        idaapi.register_action(idaapi.action_desc_t(
            self.explain_malware_action_name,
            _('Explain malware behavior'),
            ExplainMalwareBehaviorHandler(),
            "Ctrl+Alt+B",
            _("Explain the function in malware analysis context"),
            453))

        idaapi.register_action(idaapi.action_desc_t(
            self.c_code_action_name,
            _('Generate C Code'),
            GenerateCCodeHandler(),
            "Ctrl+Alt+C",
            _("Generate executable C code from the currently selected function using {model}").format(model=str(gepetto.config.model)),
            200))

        idaapi.register_action(idaapi.action_desc_t(
            self.python_code_action_name,
            _('Generate Python Code'),
            GeneratePythonCodeHandler(),
            "Ctrl+Alt+P",
            _("Generate python code from the currently selected function using {model}").format(model=str(gepetto.config.model)),
            201))

        # Attach to menu
        idaapi.attach_action_to_menu(self.explain_menu_path, self.explain_action_name, idaapi.SETMENU_APP)
        idaapi.attach_action_to_menu(self.rename_menu_path, self.rename_action_name, idaapi.SETMENU_APP)
        idaapi.attach_action_to_menu(self.rename_func_menu_path, self.rename_func_action_name, idaapi.SETMENU_APP)
        idaapi.attach_action_to_menu(self.rename_func_malware_menu_path, self.rename_func_malware_action_name, idaapi.SETMENU_APP)
        idaapi.attach_action_to_menu(self.explain_malware_menu_path, self.explain_malware_action_name, idaapi.SETMENU_APP)
        idaapi.attach_action_to_menu(self.c_code_menu_path, self.c_code_action_name, idaapi.SETMENU_APP)
        idaapi.attach_action_to_menu(self.python_code_menu_path, self.python_code_action_name, idaapi.SETMENU_APP)

        self.generate_model_select_menu()

        self.menu = ContextMenuHooks()
        self.menu.hook()

        register_cli()

        return idaapi.PLUGIN_KEEP

    def bind_model_switch_action(self, menu_path, action_name, model_name):
        action = idaapi.action_desc_t(
            action_name,
            model_name,
            None if str(gepetto.config.model) == model_name else SwapModelHandler(model_name, self),
            "",
            "",
            208 if str(gepetto.config.model) == model_name else 0)

        ida_kernwin.execute_sync(functools.partial(idaapi.register_action, action), ida_kernwin.MFF_FAST)
        ida_kernwin.execute_sync(functools.partial(idaapi.attach_action_to_menu, menu_path, action_name, idaapi.SETMENU_APP),
                                 ida_kernwin.MFF_FAST)

    def detach_actions(self):
        for provider in gepetto.models.model_manager.list_models():
            for model in provider.supported_models():
                if model in self.model_action_map:
                    ida_kernwin.execute_sync(functools.partial(idaapi.unregister_action, self.model_action_map[model]),
                                             ida_kernwin.MFF_FAST)
                    ida_kernwin.execute_sync(functools.partial(idaapi.detach_action_from_menu,
                                                               "Edit/Gepetto/" + _("Select model") +
                                                               f"/{provider.get_menu_name()}/{model}",
                                                               self.model_action_map[model]),
                                             ida_kernwin.MFF_FAST)

    def generate_model_select_menu(self):
        def do_generate_model_select_menu():
            self.detach_actions()
            for provider in gepetto.models.model_manager.list_models():
                for model in provider.supported_models():
                    self.model_action_map[model] = f"gepetto:{model}_{''.join(random.choices(string.ascii_lowercase, k=7))}"
                    self.bind_model_switch_action(
                        "Edit/Gepetto/" + _("Select model") + f"/{provider.get_menu_name()}/{model}",
                        self.model_action_map[model],
                        model)

        threading.Thread(target=do_generate_model_select_menu).start()

    def run(self, arg):
        pass

    def term(self):
        self.detach_actions()
        if self.menu:
            self.menu.unhook()
        return


class ContextMenuHooks(idaapi.UI_Hooks):
    def finish_populating_widget_popup(self, form, popup):
        if idaapi.get_widget_type(form) == idaapi.BWN_PSEUDOCODE:
            idaapi.attach_action_to_popup(form, popup, GepettoPlugin.explain_action_name, "Gepetto/")
            idaapi.attach_action_to_popup(form, popup, GepettoPlugin.rename_action_name, "Gepetto/")
            idaapi.attach_action_to_popup(form, popup, GepettoPlugin.rename_func_action_name, "Gepetto/")
            idaapi.attach_action_to_popup(form, popup, GepettoPlugin.rename_func_malware_action_name, "Gepetto/")
            idaapi.attach_action_to_popup(form, popup, GepettoPlugin.explain_malware_action_name, "Gepetto/")
            idaapi.attach_action_to_popup(form, popup, GepettoPlugin.c_code_action_name, "Gepetto/")
            idaapi.attach_action_to_popup(form, popup, GepettoPlugin.python_code_action_name, "Gepetto/")
