import sys, os, re, json, shutil, stat, getpass, hashlib, subprocess, ctypes, webbrowser
from datetime import datetime
from PyQt6 import QtWidgets, QtGui, QtCore

def resource_path(rel):
    """Resolve a bundled file path under PyInstaller (_MEIPASS) or dev run."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
# Each entry in ApplicationStorage.json -> Applications[i].Application has
# these per-game keys. Some are "Disable_*" flags we want to flip OFF, one
# (IsMultiGPUInferenceAllowed) is the new MFG / multi-GPU inference gate that
# we want flipped ON. Spec format:
#   target  - the value we want for "DLSS forced enabled"
#   abbr    - short label shown in the log summary
#   default - whether this key is toggled by default
KEY_SPECS = {
    "Disable_FG_Override":        {"target": False, "abbr": "FG",    "default": True},
    "Disable_RR_Override":        {"target": False, "abbr": "RR",    "default": True},
    "Disable_SR_Override":        {"target": False, "abbr": "SR",    "default": True},
    "Disable_RR_Model_Override":  {"target": False, "abbr": "RR-M",  "default": True},
    "Disable_SR_Model_Override":  {"target": False, "abbr": "SR-M",  "default": True},
    "DLSS_Override_No_OPS":       {"target": False, "abbr": "NoOPS", "default": True},
    "IsMultiGPUInferenceAllowed": {"target": True,  "abbr": "MFG",   "default": True},
    # Opt-in: NVIDIA App may overwrite this from the cloud-side cms_appId list.
    "IsOpsSupported":             {"target": True,  "abbr": "OPS",   "default": False},
}

def _tip_key_for(abbr):
    """Map an abbreviation like 'RR-M' to its LANG tip key 'tip_RR_M'."""
    return f"tip_{abbr.replace('-', '_')}"

def _label_key_for(abbr):
    """Map an abbreviation like 'RR-M' to its LANG label key 'key_RR_M_label'."""
    return f"key_{abbr.replace('-', '_')}_label"

# fingerprint.db (cloud-seed XML template) uses 1/0 instead of true/false and
# only contains a subset of the keys. We flip 1 -> 0 only for the Disable_*
# keys; IsMultiGPUInferenceAllowed lives only in ApplicationStorage.json.
FINGERPRINT_XML_KEYS = [
    "Disable_FG_Override", "Disable_RR_Override", "Disable_SR_Override",
    "Disable_RR_Model_Override", "Disable_SR_Model_Override",
    "DLSS_Override_No_OPS",
]

# Latest known good Streamline SDK version. DLSS 4 MFG starts ~2.7.10,
# DLSS 4.5 with 6x MFG / 2nd-gen transformer needs 2.7.32+.
DEFAULT_LATEST_SL_VERSION = "2.7.32"

# NVIDIA App services in dependency order (stop reverse, start forward).
NVIDIA_SERVICES = [
    "NVDisplay.ContainerLocalSystem",
    "NvContainerLocalSystem",
]

# Documented driver-side override IDs (NVAPI / nvidiaProfileInspector).
# These cannot be set via ApplicationStorage.json - they live in the driver
# profile DB and require nvidiaProfileInspector or NVAPI calls.
NPI_INFO = [
    ("0x104D6667", "DLSS-MFG Fixed Frame Generation Count",   "0=N/A,1=2x,2=3x,3=4x,4=5x,5=6x"),
    ("0x10562D0F", "DLSS-MFG Dynamic Frame Generation Count", "0=N/A,2=Up to 2x,3=3x,...,6=6x"),
    ("0x10CF4125", "DLSS-MFG Target Dynamic Frame Rate",      "0x3C..0x1F4=60..500 fps, 0x01000000=max"),
    ("0x10308298", "DLSS-FG Forced Mode",                     "0=N/A, 2=Fixed, 4=Dynamic"),
    ("0x10E41DF1", "DLSS-FG Forced Preset Letter",            "0=N/A, 1=A, 2=B, 0x00FFFFFE=Recommended"),
    ("0x10E41DF3", "DLSS-SR Forced Preset Letter",            "5=E, 6=F, 0xA=J, 0x00FFFFFF=K (DLSS 4)"),
    ("0x10E41DF4", "DLSS-SR Force all levels to DLAA",        "0=Off, 1=On"),
    ("0x10E41DF5", "DLSS-SR Forced scaling ratio",            "float32 hex"),
    ("0x10E41DF7", "DLSS-RR Forced Render Preset",            "preset selector"),
]
NPI_RELEASES_URL = "https://github.com/Orbmu2k/nvidiaProfileInspector/releases"

# Donation info (embedded in app's right sidebar).
DONATE_PIX_KEY = "8cd6bf4a-6288-4535-a5fd-78dce11e3568"
DONATE_BEP20_ADDR = "0x724ec14cbfabdf7bb07653bd73298ca1a4730ffb"
DONATE_PAYPAL_URL = "https://www.paypal.com/donate/?business=47E2WRE9G99U2&currency_code=BRL"

# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------
LANG = {
    "PT": {
        "window_title": "DLSS Override Editor v{v} (MFG-ready)",
        "browse": "Procurar",
        "status_writable": "Status do arquivo: GRAVÁVEL (NVIDIA App pode atualizar)",
        "status_readonly": "Status do arquivo: SOMENTE LEITURA (protegido contra updates)",
        "status_not_found": "Arquivo não encontrado",
        "keys_group": "Chaves a aplicar (ApplicationStorage.json)",
        "extra_group": "Opções extras",
        "sl_label": "Atualizar versão da Streamline SDK (DLSS runtime) para:",
        "sl_scan": "Escanear arquivo (max)",
        "sl_help": "<i>Se não souber, deixe desmarcado. 'Escanear' lê a maior versão presente no seu JSON.</i>",
        "patch_fp": "Também editar fingerprint.db (template cloud-seed)",
        "set_ro": "Marcar arquivo como somente leitura após mudanças",
        "dlss_indicator": "Ativar indicador DLSS na tela (NGXCore, requer admin)",
        "preview": "Pré-visualizar",
        "process": "Processar Arquivo",
        "revert": "Reverter do Backup",
        "make_ro": "Travar (Read-Only)",
        "make_rw": "Destravar (Writable)",
        "restart_svc": "Reiniciar Serviços NVIDIA",
        "npi_btn": "Overrides do driver (NPI)",
        "clear_log": "Limpar Log",
        "donate_title": "☕ Curtiu? Apoie",
        "donate_subtitle": "Mantém o projeto vivo",
        "donate_pix": "Copiar chave PIX",
        "donate_bep20": "Copiar endereço cripto",
        "donate_paypal": "Doar via PayPal",
        "copied": "✓ Copiado!",
        "log_init": "DLSS Override Editor v{v} iniciado",
        "log_target": "Arquivo alvo: {p}",
        "log_nvapp": "Versão NVIDIA App: {v}",
        "log_gpu": "Família da GPU: {g}",
        "log_note_untested": "OBS: testado contra v{v}.x; pré-visualize antes de aplicar.",
        "log_note_mfg": "OBS: MFG 3x/4x/5x/6x requer RTX série 50. A flag JSON é setada, mas runtime fica em 2x DLSS-FG em {g}.",
        "log_sl_detected": "Versão Streamline SDK detectada: {v}",
        "lang_switch_log": "Idioma alterado para: Português",
        # --- Tooltips (linguagem simples, sem jargão) ---
        "tip_pt_btn": "Mudar idioma do programa para Português",
        "tip_en_btn": "Switch program language to English",
        "tip_path": "Caminho do arquivo que será editado. Por padrão aponta para o arquivo correto da NVIDIA App. Só altere se você sabe o que está fazendo.",
        "tip_browse": "Abre uma janela para escolher outro arquivo manualmente. Normalmente não é necessário.",
        "tip_FG": "Libera a opção 'Frame Generation' nas configurações DLSS da NVIDIA App. Frame Gen cria quadros extras com IA para aumentar o FPS. Requer GPU RTX 40 ou 50.",
        "tip_RR": "Libera a opção 'Ray Reconstruction' (RR). É um denoiser de IA que melhora a qualidade do ray tracing em jogos. Funciona em qualquer placa RTX.",
        "tip_SR": "Libera o 'Super Resolution' (DLSS clássico). Renderiza o jogo em resolução menor e usa IA para reconstruir em resolução cheia — mais FPS sem perder muita qualidade.",
        "tip_RR_M": "Permite trocar o modelo de IA usado pelo Ray Reconstruction. O modelo Transformer (novo) é melhor que o CNN antigo.",
        "tip_SR_M": "Permite trocar o modelo de IA usado pelo DLSS Super Resolution. O Preset K (Transformer 2nd-gen) é o melhor disponível em 2026.",
        "tip_NoOPS": "Faz os overrides DLSS funcionarem mesmo em jogos que NÃO estão no banco oficial da NVIDIA. Deixe ATIVO — é o que destrava jogos 'não suportados'.",
        "tip_MFG": "Libera 'Multi-Frame Generation' — gera múltiplos quadros extras (3x, 4x, 6x). Recurso principal da série RTX 50. Em RTX 40, fica limitado a 2x.",
        "tip_OPS": "Faz o programa MENTIR para a NVIDIA App, dizendo que todos os jogos têm perfil oficial. PODE REVERTER sozinho. Deixe desativado a menos que algum jogo específico esteja com toggles travados.",
        "tip_sl_cb": "Atualiza a versão da biblioteca DLSS pinada para cada jogo. Versões mais novas destravam mais recursos. RISCO: se a NVIDIA App não tem a versão instalada, pode quebrar o DLSS. Em caso de dúvida, deixe desmarcado.",
        "tip_sl_edit": "Versão a aplicar (ex: 2.7.32 = DLSS 4.5). O programa já preenche automaticamente com a maior versão presente no seu arquivo, então é seguro.",
        "tip_sl_scan": "Lê o seu arquivo e preenche o campo com a maior versão DLSS já presente. Sempre seguro usar esse valor.",
        "tip_patch_fp": "Edita um segundo arquivo da NVIDIA que controla como JOGOS NOVOS detectados começam. Sem isso, jogos novos virão com DLSS travado de novo. Mantenha ativo.",
        "tip_readonly_cb": "No fim do processo, marca o arquivo como 'somente leitura' para a NVIDIA App não desfazer suas mudanças. Importante: se for instalar jogo novo depois, precisa desmarcar primeiro (botão 'Destravar').",
        "tip_dlss_indicator": "Mostra um pequeno texto verde no canto da tela em jogos com DLSS ativo, indicando que está funcionando. REQUER abrir o programa como Administrador (clique direito no .exe → 'Executar como administrador').",
        "tip_preview": "Mostra no log o que SERIA mudado, sem gravar nada. 100% seguro — só leitura. Use antes de processar se quiser ter certeza.",
        "tip_process": "BOTÃO PRINCIPAL. Aplica todas as mudanças marcadas acima ao arquivo da NVIDIA. Cria backup automático antes. Depois clique em 'Reiniciar Serviços NVIDIA' para a NVIDIA App carregar.",
        "tip_revert": "Desfaz TUDO que o programa fez. Restaura do backup automático. Use se algo deu errado ou quiser voltar ao original.",
        "tip_make_ro": "Tranca o arquivo da NVIDIA como 'somente leitura' para impedir a NVIDIA App de reverter suas mudanças.",
        "tip_make_rw": "Destrava o arquivo da NVIDIA. Use SE for instalar um jogo novo (a NVIDIA App precisa escrever no arquivo para detectar o jogo). Depois rode 'Processar Arquivo' de novo.",
        "tip_restart_svc": "Reinicia os serviços da NVIDIA para carregar suas mudanças sem precisar reiniciar o PC. A tela pode piscar 1-2 segundos. Vai pedir UAC — clique Sim.",
        "tip_npi_btn": "Abre uma tela com informações sobre o nvidiaProfileInspector — programa AVANÇADO separado que permite forçar coisas como o multiplicador exato do MFG (3x, 4x, 6x) e o Preset K do DLSS 4. Esse botão só mostra info.",
        "tip_clear_log": "Limpa o histórico de mensagens da área preta abaixo. Útil para começar uma execução nova sem ruído da anterior.",
        "tip_donate_pix": "Copia a chave PIX (Brasil) para você colar no app do seu banco. Doação ajuda a manter o projeto vivo!",
        "tip_donate_bep20": "Copia o endereço da carteira BSC/BEP20 (cripto). Aceita USDT, USDC, BTCB, BUSD na rede Binance Smart Chain. NÃO envie Bitcoin nativo.",
        "tip_donate_paypal": "Abre o PayPal no navegador para fazer uma doação por cartão ou conta PayPal. Aceita cartão sem precisar ter conta PayPal.",
        # Checkbox labels (visible text next to each key checkbox)
        "key_FG_label": "FG — Frame Generation (gera quadros extras por IA)",
        "key_RR_label": "RR — Ray Reconstruction (denoiser de IA para ray tracing)",
        "key_SR_label": "SR — Super Resolution (DLSS clássico — mais FPS)",
        "key_RR_M_label": "RR-M — Modelo do Ray Reconstruction (escolher Transformer)",
        "key_SR_M_label": "SR-M — Modelo do Super Resolution (Preset K / Transformer)",
        "key_NoOPS_label": "NoOPS — Liberar mesmo em jogos sem perfil cloud (essencial)",
        "key_MFG_label": "MFG — Multi-Frame Gen (3x/4x/6x — DLSS 4 / RTX 50)",
        "key_OPS_label": "OPS — [Agressivo] Forçar suporte OPS (pode reverter)",
        # --- Dialog titles and messages ---
        "dlg_error_title": "Erro",
        "dlg_error_file_not_found": "Arquivo não encontrado:\n{p}",
        "dlg_error_read_json": "Falha ao ler o JSON:\n{e}",
        "dlg_browse_title": "Selecione o arquivo ApplicationStorage.json",
        "dlg_restart_title": "Reiniciar Serviços NVIDIA",
        "dlg_restart_msg": "Isso vai reiniciar os serviços de vídeo e container da NVIDIA.\nPode causar um breve piscar de tela.\n\nContinuar?",
        "dlg_nothing_title": "Nada selecionado",
        "dlg_nothing_msg": "Marque pelo menos uma chave ou ative o bump da versão da Streamline SDK.",
        "dlg_process_title": "Confirmar Processamento",
        "dlg_process_msg": "Aplicar {n} chave(s) {sl}em:\n\n{p}\n\nContinuar?",
        "dlg_process_sl_extra": "mais bump da versão Streamline SDK ",
        "dlg_revert_title": "Confirmar Reversão",
        "dlg_revert_msg": "Restaurar o arquivo original do backup?\n\n{p}",
        "dlg_close_title": "Ação Necessária",
        "dlg_close_msg": "As mudanças exigem reiniciar serviços ou o PC para terem efeito.\nO que deseja fazer?",
        "dlg_close_restart": "Reiniciar Serviços",
        "dlg_close_reboot": "Reiniciar PC",
        "dlg_close_nothing": "Não fazer nada",
        "dlg_reboot_confirm_title": "Confirmar Reboot",
        "dlg_reboot_confirm_msg": "Reiniciar o PC agora? Trabalho não salvo em outros programas será perdido.",
        # NPI Info dialog
        "npi_title": "Overrides do driver (nvidiaProfileInspector)",
        "npi_intro": "O ApplicationStorage.json controla quais toggles DLSS aparecem na interface\nda NVIDIA App. Para forçar os valores que o driver aplica em tempo de execução\n(principalmente o multiplicador do MFG e o Preset K/J do DLSS), use esses\nIDs no nvidiaProfileInspector. As edições do JSON e os IDs do driver são\ncamadas independentes — ambos devem estar configurados para controle total.",
        "npi_col_id": "ID da Configuração",
        "npi_col_name": "Nome",
        "npi_col_values": "Valores",
        "npi_open_btn": "Abrir página de releases do NPI",
        "npi_close_btn": "Fechar",
        # Log messages (user-facing)
        "log_selected_file": "Arquivo selecionado: {p}",
        "log_removing_ro": "Removendo proteção somente leitura...",
        "log_can_add_games": "Agora você pode adicionar/atualizar jogos na NVIDIA App",
        "log_setting_ro": "Aplicando proteção somente leitura...",
        "log_protected": "Arquivo agora está protegido contra updates da NVIDIA App",
        "log_op_cancelled": "Operação cancelada pelo usuário",
        "log_starting_process": "Iniciando processamento do arquivo...",
        "log_revert_cancelled": "Reversão cancelada pelo usuário",
        "log_starting_revert": "Iniciando reversão...",
    },
    "EN": {
        "window_title": "DLSS Override Editor v{v} (MFG-ready)",
        "browse": "Browse",
        "status_writable": "File Status: WRITABLE (NVIDIA App can update this file)",
        "status_readonly": "File Status: READ-ONLY (protected from NVIDIA App updates)",
        "status_not_found": "File not found",
        "keys_group": "Keys to apply (ApplicationStorage.json)",
        "extra_group": "Extra options",
        "sl_label": "Update Streamline SDK version (DLSS runtime) to:",
        "sl_scan": "Scan file for max",
        "sl_help": "<i>If unsure, leave unchecked. 'Scan file for max' reads the highest version already in your JSON.</i>",
        "patch_fp": "Also patch fingerprint.db (cloud-seed template)",
        "set_ro": "Set file as read-only after modifications",
        "dlss_indicator": "Enable DLSS on-screen indicator (NGXCore, admin)",
        "preview": "Preview",
        "process": "Process File",
        "revert": "Revert to Backup",
        "make_ro": "Make Read-Only",
        "make_rw": "Make Writable",
        "restart_svc": "Restart NVIDIA Services",
        "npi_btn": "Driver-side overrides (NPI)",
        "clear_log": "Clear Log",
        "donate_title": "☕ Liked it? Support",
        "donate_subtitle": "Keeps the project alive",
        "donate_pix": "Copy PIX key",
        "donate_bep20": "Copy crypto address",
        "donate_paypal": "Donate via PayPal",
        "copied": "✓ Copied!",
        "log_init": "DLSS Override Editor v{v} initialized",
        "log_target": "Target file: {p}",
        "log_nvapp": "NVIDIA App version: {v}",
        "log_gpu": "GPU family: {g}",
        "log_note_untested": "NOTE: tested against v{v}.x; verify keys by previewing before applying.",
        "log_note_mfg": "NOTE: MFG 3x/4x/5x/6x requires RTX 50-series. JSON flag still gets set, but runtime will cap at 2x DLSS-FG on {g}.",
        "log_sl_detected": "Detected current Streamline SDK version: {v}",
        "lang_switch_log": "Language switched to: English",
        # --- Tooltips (plain language, no jargon) ---
        "tip_pt_btn": "Switch program language to Portuguese",
        "tip_en_btn": "Switch program language to English",
        "tip_path": "Path of the file that will be edited. Defaults to NVIDIA App's correct location. Only change this if you know what you're doing.",
        "tip_browse": "Open a window to manually pick a different file. Usually not needed.",
        "tip_FG": "Unlocks the 'Frame Generation' option in NVIDIA App's DLSS settings. Frame Gen creates extra frames with AI to boost FPS. Requires RTX 40 or 50 GPU.",
        "tip_RR": "Unlocks 'Ray Reconstruction' (RR). An AI denoiser that improves ray tracing quality. Works on any RTX card.",
        "tip_SR": "Unlocks 'Super Resolution' (classic DLSS). Renders the game at lower res and uses AI to reconstruct full res — more FPS without much quality loss.",
        "tip_RR_M": "Lets you change the AI model used by Ray Reconstruction. The new Transformer model is better than the old CNN.",
        "tip_SR_M": "Lets you change the AI model used by DLSS Super Resolution. Preset K (Transformer 2nd-gen) is the best available in 2026.",
        "tip_NoOPS": "Makes DLSS overrides work even on games NOT in NVIDIA's official database. Keep ON — this is what unlocks 'unsupported' games.",
        "tip_MFG": "Unlocks 'Multi-Frame Generation' — creates multiple extra frames (3x, 4x, 6x). The flagship RTX 50 feature. On RTX 40 it caps at 2x.",
        "tip_OPS": "Makes the program LIE to NVIDIA App, claiming every game has an official profile. CAN REVERT itself. Leave off unless a specific game has its toggles locked.",
        "tip_sl_cb": "Updates the pinned DLSS library version for each game. Newer versions unlock more features. RISK: if NVIDIA App doesn't have that version installed, it can break DLSS. When in doubt, leave unchecked.",
        "tip_sl_edit": "Version to apply (e.g. 2.7.32 = DLSS 4.5). The program auto-fills with the highest version present in your file, so this is safe.",
        "tip_sl_scan": "Reads your file and fills the field with the highest DLSS version already present. Always safe to use this value.",
        "tip_patch_fp": "Edits a second NVIDIA file that controls how NEWLY-DETECTED games start. Without this, future-installed games will come with DLSS locked again. Keep ON.",
        "tip_readonly_cb": "After processing, marks the file as 'read-only' so NVIDIA App can't undo your changes. Important: if you install a NEW game later, you need to uncheck this first (use the 'Make Writable' button).",
        "tip_dlss_indicator": "Shows a small green text in the screen corner in games with DLSS active, indicating it's working. REQUIRES opening the program as Administrator (right-click the .exe → 'Run as administrator').",
        "tip_preview": "Shows in the log what WOULD change, without saving anything. 100% safe — read-only. Use before processing if you want to double-check.",
        "tip_process": "MAIN BUTTON. Applies all the changes selected above to NVIDIA's file. Creates an automatic backup first. After clicking, use 'Restart NVIDIA Services' so NVIDIA App loads the changes.",
        "tip_revert": "Undoes EVERYTHING this app did. Restores from the automatic backup. Use if something went wrong or you want to return to NVIDIA's original.",
        "tip_make_ro": "Locks NVIDIA's file as 'read-only' to prevent NVIDIA App from reverting your changes.",
        "tip_make_rw": "Unlocks NVIDIA's file. Use IF you're going to install a new game (NVIDIA App needs to write to the file to detect it). Then run 'Process File' again.",
        "tip_restart_svc": "Restarts NVIDIA services to load your changes without rebooting your PC. Screen may flicker 1-2 seconds. Will ask for UAC — click Yes.",
        "tip_npi_btn": "Opens a screen with info about nvidiaProfileInspector — separate ADVANCED program that lets you force things like exact MFG multiplier (3x, 4x, 6x) and DLSS 4 Preset K. This button only shows info.",
        "tip_clear_log": "Clears the message history from the black area below. Useful to start a fresh run without noise from the previous one.",
        "tip_donate_pix": "Copies the PIX key (Brazil) so you can paste it in your bank's app. Donations keep the project alive!",
        "tip_donate_bep20": "Copies the BSC/BEP20 wallet address (crypto). Accepts USDT, USDC, BTCB, BUSD on Binance Smart Chain. DO NOT send native Bitcoin.",
        "tip_donate_paypal": "Opens PayPal in your browser to make a donation by card or PayPal account. Accepts card without needing an account.",
        # Checkbox labels
        "key_FG_label": "FG — Frame Generation (AI-generated extra frames)",
        "key_RR_label": "RR — Ray Reconstruction (AI denoiser for ray tracing)",
        "key_SR_label": "SR — Super Resolution (classic DLSS — more FPS)",
        "key_RR_M_label": "RR-M — Ray Reconstruction model (pick Transformer)",
        "key_SR_M_label": "SR-M — Super Resolution model (Preset K / Transformer)",
        "key_NoOPS_label": "NoOPS — Unlock games without cloud profile (essential)",
        "key_MFG_label": "MFG — Multi-Frame Gen (3x/4x/6x — DLSS 4 / RTX 50)",
        "key_OPS_label": "OPS — [Aggressive] Force OPS support (can revert)",
        # --- Dialog titles and messages ---
        "dlg_error_title": "Error",
        "dlg_error_file_not_found": "File not found:\n{p}",
        "dlg_error_read_json": "Reading JSON failed:\n{e}",
        "dlg_browse_title": "Select ApplicationStorage.json file",
        "dlg_restart_title": "Restart NVIDIA Services",
        "dlg_restart_msg": "This will restart NVIDIA display and container services.\nMay cause a brief screen flicker.\n\nContinue?",
        "dlg_nothing_title": "Nothing selected",
        "dlg_nothing_msg": "Pick at least one key or enable the Streamline SDK version bump.",
        "dlg_process_title": "Confirm Process",
        "dlg_process_msg": "Apply {n} key(s) {sl}to:\n\n{p}\n\nContinue?",
        "dlg_process_sl_extra": "plus Streamline SDK version bump ",
        "dlg_revert_title": "Confirm Revert",
        "dlg_revert_msg": "Restore the original file from backup?\n\n{p}",
        "dlg_close_title": "Action Required",
        "dlg_close_msg": "Changes require restarting services or rebooting to take effect.\nWhat would you like to do?",
        "dlg_close_restart": "Restart Services",
        "dlg_close_reboot": "Reboot PC",
        "dlg_close_nothing": "Do Nothing",
        "dlg_reboot_confirm_title": "Confirm Reboot",
        "dlg_reboot_confirm_msg": "Reboot now? Unsaved work in other apps will be lost.",
        # NPI Info dialog
        "npi_title": "Driver-side overrides (nvidiaProfileInspector)",
        "npi_intro": "ApplicationStorage.json gates which DLSS toggles appear in the\nNVIDIA App UI. To force the values the driver applies at runtime\n(especially MFG multiplier and DLSS Preset K/J), use these IDs in\nnvidiaProfileInspector. The JSON edits and these driver IDs are\nindependent layers — both should match for full control.",
        "npi_col_id": "Setting ID",
        "npi_col_name": "Name",
        "npi_col_values": "Values",
        "npi_open_btn": "Open NPI releases page",
        "npi_close_btn": "Close",
        # Log messages (user-facing)
        "log_selected_file": "Selected file: {p}",
        "log_removing_ro": "Removing read-only protection...",
        "log_can_add_games": "You can now add/update games in NVIDIA App",
        "log_setting_ro": "Setting read-only protection...",
        "log_protected": "File is now protected from NVIDIA App updates",
        "log_op_cancelled": "Operation cancelled by user",
        "log_starting_process": "Starting file processing...",
        "log_revert_cancelled": "Revert cancelled by user",
        "log_starting_revert": "Starting revert operation...",
    },
}

# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------
def compute_file_hash(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except Exception as e:
        print(f"Error computing hash: {e}")
    return h.hexdigest()

def is_read_only(path):
    try:
        return not os.access(path, os.W_OK)
    except Exception:
        return False

def make_writable(path):
    if os.path.exists(path) and is_read_only(path):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)

def set_read_only(path, readonly, log_func):
    try:
        if readonly:
            os.chmod(path, stat.S_IREAD)
            log_func("File set to READ-ONLY")
        else:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            log_func("File set to WRITABLE")
        return True
    except Exception as e:
        log_func(f"ERROR: Failed to change file permissions: {e}")
        return False

# ---------------------------------------------------------------------------
# Backup / meta
# ---------------------------------------------------------------------------
def create_backup(main_path, backup_path, meta_path, log_func):
    try:
        make_writable(main_path)
        make_writable(backup_path)
        make_writable(meta_path)
        shutil.copy2(main_path, backup_path)
        original_hash = compute_file_hash(main_path)
        meta = {"original_hash": original_hash, "modified_hash": original_hash}
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        log_func(f"Backup created: {os.path.basename(backup_path)}")
        return meta
    except Exception as e:
        log_func(f"ERROR: Creating backup failed: {e}")
        return None

def load_backup_meta(meta_path):
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_backup_meta(meta_path, meta):
    try:
        make_writable(meta_path)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)
    except Exception as e:
        print(f"Error saving backup meta: {e}")

def update_backup_if_obsolete(main_path, backup_path, meta_path, log_func):
    if not os.path.exists(backup_path) or not os.path.exists(meta_path):
        log_func("No existing backup found, creating new backup...")
        return create_backup(main_path, backup_path, meta_path, log_func)
    meta = load_backup_meta(meta_path)
    if meta is None:
        log_func("Backup metadata invalid, creating new backup...")
        return create_backup(main_path, backup_path, meta_path, log_func)
    current_hash = compute_file_hash(main_path)
    if current_hash != meta.get("modified_hash"):
        log_func("NVIDIA App updated the file externally - refreshing backup baseline")
        return create_backup(main_path, backup_path, meta_path, log_func)
    log_func("Backup is current, no update needed")
    return meta

# ---------------------------------------------------------------------------
# ApplicationStorage.json processing
# ---------------------------------------------------------------------------
def _apply_to_app_dict(app_obj, identifier, enabled_keys, pinned_sl_version, updates, stats):
    """Apply key flips to a single Application dict. Returns whether modified."""
    modified = False
    for key, spec in KEY_SPECS.items():
        if key not in enabled_keys:
            continue
        if key not in app_obj:
            continue
        stats["total_keys_found"] += 1
        target = spec["target"]
        if app_obj[key] == target:
            stats["already_correct"] += 1
            continue
        app_obj[key] = target
        modified = True
        stats["keys_changed"] += 1
        updates.setdefault(identifier, set()).add(spec["abbr"])

    if pinned_sl_version and "PinnedSLVersion" in app_obj:
        if app_obj["PinnedSLVersion"] != pinned_sl_version:
            app_obj["PinnedSLVersion"] = pinned_sl_version
            modified = True
            updates.setdefault(identifier, set()).add(f"SL={pinned_sl_version}")
    return modified

def recursive_process(obj, enabled_keys, pinned_sl_version, updates, stats, depth=0):
    """Walk the JSON tree. Apply key flips inside each Application dict."""
    modified = False
    if isinstance(obj, dict):
        # An Applications[i] entry has the shape {"LocalId": N, "Application": {...}}.
        wrapper_processed = False
        if "Application" in obj and isinstance(obj["Application"], dict):
            app = obj["Application"]
            identifier = app.get("DisplayName") or app.get("ShortName") or obj.get("LocalId") or "Unknown"
            if _apply_to_app_dict(app, identifier, enabled_keys, pinned_sl_version, updates, stats):
                modified = True
            wrapper_processed = True
        else:
            # Some shapes may put keys directly on this dict (defensive).
            identifier = obj.get("DisplayName") or obj.get("LocalId") or "Unknown"
            if any(k in obj for k in KEY_SPECS):
                if _apply_to_app_dict(obj, identifier, enabled_keys, pinned_sl_version, updates, stats):
                    modified = True
        for k, value in obj.items():
            # Don't recurse into the Application sub-dict we just processed -
            # that would double-count its keys.
            if wrapper_processed and k == "Application":
                continue
            if isinstance(value, (dict, list)):
                if recursive_process(value, enabled_keys, pinned_sl_version, updates, stats, depth + 1):
                    modified = True
    elif isinstance(obj, list):
        # Count apps_scanned only at the top-level Applications array.
        if depth == 1:
            stats["apps_scanned"] = len(obj)
        for item in obj:
            if isinstance(item, (dict, list)):
                if recursive_process(item, enabled_keys, pinned_sl_version, updates, stats, depth + 1):
                    modified = True
    return modified

def scan_max_sl_version(path):
    """Find the highest PinnedSLVersion string in the file (textual max-by-tuple)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None
    versions = re.findall(r'"PinnedSLVersion"\s*:\s*"([^"]+)"', content)
    if not versions:
        return None
    def as_tuple(v):
        parts = []
        for p in v.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return tuple(parts)
    return max(versions, key=as_tuple)

def modify_file(main_path, enabled_keys, pinned_sl_version, log_func):
    backup_path = main_path + ".backup"
    meta_path = main_path + ".backup.meta"

    was_readonly = is_read_only(main_path)
    if was_readonly:
        log_func("File is read-only, temporarily making writable...")
        try:
            os.chmod(main_path, stat.S_IWRITE | stat.S_IREAD)
        except Exception as e:
            log_func(f"ERROR: Cannot make file writable: {e}")
            return False, None, was_readonly

    meta = update_backup_if_obsolete(main_path, backup_path, meta_path, log_func)
    if meta is None:
        log_func("WARNING: Backup creation failed, continuing without backup tracking")
        meta = {"original_hash": "", "modified_hash": ""}

    try:
        with open(main_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log_func(f"ERROR: Reading JSON failed: {e}")
        return False, None, was_readonly

    updates = {}
    stats = {"total_keys_found": 0, "keys_changed": 0, "already_correct": 0, "apps_scanned": 0}
    modified = recursive_process(data, enabled_keys, pinned_sl_version, updates, stats)

    log_func("--- Scan Results ---")
    log_func(f"Applications scanned: {stats['apps_scanned']}")
    log_func(f"Tracked keys found: {stats['total_keys_found']}")
    log_func(f"Keys changed to target: {stats['keys_changed']}")
    log_func(f"Keys already at target: {stats['already_correct']}")

    if modified:
        try:
            make_writable(main_path)
            with open(main_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            log_func("--- Changes Applied ---")
            mod_hash = compute_file_hash(main_path)
            meta["modified_hash"] = mod_hash
            save_backup_meta(meta_path, meta)
        except Exception as e:
            log_func(f"ERROR: Writing JSON failed: {e}")
            return False, None, was_readonly
        for app, changes in updates.items():
            log_func(f"  {app}: {', '.join(sorted(changes))}")
        log_func("Restart NVIDIA services or reboot for changes to take effect")
    else:
        log_func("--- No Changes Needed ---")
        log_func("All tracked keys are already at the target values")

    return modified, meta, was_readonly

def revert_file(main_path, log_func):
    backup_path = main_path + ".backup"
    meta_path = main_path + ".backup.meta"
    if not os.path.exists(backup_path) or not os.path.exists(meta_path):
        log_func("ERROR: No backup available to revert")
        return False
    meta = load_backup_meta(meta_path)
    current_hash = compute_file_hash(main_path)
    if current_hash != meta.get("modified_hash"):
        log_func("WARNING: File was externally modified since last update")
        log_func("Cannot revert - backup may be outdated")
        return False
    try:
        make_writable(main_path)
        shutil.copy2(backup_path, main_path)
        log_func("Reverted to backup successfully")
        meta["modified_hash"] = meta["original_hash"]
        save_backup_meta(meta_path, meta)
        return True
    except Exception as e:
        log_func(f"ERROR: Revert failed: {e}")
        return False

# ---------------------------------------------------------------------------
# fingerprint.db (XML cloud-seed) patching
# ---------------------------------------------------------------------------
# NVIDIA App reads NvBackend/ApplicationOntology/data/fingerprint.db on launch
# and uses it to seed ApplicationStorage.json for newly detected games. If we
# don't also flip the Disable_* tags here, the App will keep re-applying old
# defaults whenever a new game gets fingerprinted.
def fingerprint_path_for(app_storage_path):
    base = os.path.dirname(app_storage_path)  # ...\NvBackend
    return os.path.join(base, "ApplicationOntology", "data", "fingerprint.db")

def patch_fingerprint_db(fp_path, enabled_keys, log_func):
    if not os.path.exists(fp_path):
        log_func(f"fingerprint.db not found at: {fp_path}")
        return False
    try:
        backup = fp_path + ".backup"
        if not os.path.exists(backup):
            make_writable(fp_path)
            shutil.copy2(fp_path, backup)
            log_func(f"fingerprint.db backup created: {os.path.basename(backup)}")
        make_writable(fp_path)
        with open(fp_path, "r", encoding="utf-8") as f:
            xml = f.read()
        total_changed = 0
        for key in FINGERPRINT_XML_KEYS:
            if key not in enabled_keys:
                continue
            pattern = re.compile(rf"<{key}>1</{key}>")
            xml, n = pattern.subn(f"<{key}>0</{key}>", xml)
            if n:
                log_func(f"  fingerprint.db: <{key}> 1->0 ({n} occurrences)")
                total_changed += n
        with open(fp_path, "w", encoding="utf-8") as f:
            f.write(xml)
        log_func(f"fingerprint.db patched ({total_changed} tag flips total)")
        return True
    except Exception as e:
        log_func(f"ERROR: fingerprint.db patch failed: {e}")
        return False

# ---------------------------------------------------------------------------
# NGX registry tweaks
# ---------------------------------------------------------------------------
def set_dlss_indicator(enabled, log_func):
    """ShowDlssIndicator: 0x400 (1024) = on-screen indicator, 0x0 = off."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\NVIDIA Corporation\Global\NGXCore",
                             0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
        winreg.SetValueEx(key, "ShowDlssIndicator", 0, winreg.REG_DWORD,
                          0x400 if enabled else 0x0)
        winreg.CloseKey(key)
        log_func(f"NGXCore ShowDlssIndicator set to {'ON (0x400)' if enabled else 'OFF (0x0)'}")
        return True
    except PermissionError:
        log_func("ERROR: Need admin to write NGXCore registry. Right-click -> Run as administrator")
        return False
    except Exception as e:
        log_func(f"ERROR: Setting NGX registry failed: {e}")
        return False

# ---------------------------------------------------------------------------
# Service control
# ---------------------------------------------------------------------------
def restart_services(log_func):
    """Stop both services first (reverse dependency), then start both."""
    stop_cmds = [f'net stop "{s}"' for s in reversed(NVIDIA_SERVICES)]
    start_cmds = [f'net start "{s}"' for s in NVIDIA_SERVICES]
    chain = " & ".join(stop_cmds + start_cmds)
    cmd = f"/c {chain}"
    log_func("--- Restarting NVIDIA Services ---")
    if ctypes.windll.shell32.IsUserAnAdmin():
        result = subprocess.run("cmd.exe " + cmd, shell=True, capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                text=True, encoding="utf-8", errors="replace")
        for stream_name, stream in (("OUT", result.stdout), ("ERR", result.stderr)):
            if stream:
                for line in stream.strip().split("\n"):
                    if line.strip():
                        prefix = "  ERROR: " if stream_name == "ERR" else "  "
                        log_func(prefix + line.strip())
        log_func("Services restart completed")
    else:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd, None, 0)
        if ret <= 32:
            log_func("ERROR: Failed to launch elevated command")
        else:
            log_func("UAC prompt opened - approve to restart services")

# ---------------------------------------------------------------------------
# System probing (for warnings)
# ---------------------------------------------------------------------------
def detect_nvidia_app_version():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\NVIDIA Corporation\Global\NvApp",
                             0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        version, _ = winreg.QueryValueEx(key, "Version")
        winreg.CloseKey(key)
        return version
    except Exception:
        return None

def _classify_gpu_name(name):
    n = (name or "").upper()
    if any(t in n for t in ("RTX 50", "RTX 5090", "RTX 5080", "RTX 5070", "RTX 5060")):
        return "RTX 50"
    if any(t in n for t in ("RTX 40", "RTX 4090", "RTX 4080", "RTX 4070", "RTX 4060")):
        return "RTX 40"
    if "RTX 30" in n: return "RTX 30"
    if "RTX 20" in n: return "RTX 20"
    return None

def detect_gpu_generation():
    """Return rough GPU family: 'RTX 50', 'RTX 40', 'RTX 30', or None.
    Uses PowerShell Get-CimInstance (wmic was removed in Windows 11 24H2+)."""
    # Try registry first - fastest, no subprocess
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
                             0, winreg.KEY_READ)
        name, _ = winreg.QueryValueEx(key, "DriverDesc")
        winreg.CloseKey(key)
        gen = _classify_gpu_name(name)
        if gen:
            return gen
    except Exception:
        pass
    # PowerShell fallback (works on all Windows 10/11 versions)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return _classify_gpu_name(result.stdout)
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class CloseActionDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Use parent's translator if available
        t = getattr(parent, "_t", None) or (lambda k, **kw: k)
        self.setWindowTitle(t("dlg_close_title"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(t("dlg_close_msg")))
        row = QtWidgets.QHBoxLayout()
        self.restartButton = QtWidgets.QPushButton(t("dlg_close_restart"))
        self.rebootButton = QtWidgets.QPushButton(t("dlg_close_reboot"))
        self.noActionButton = QtWidgets.QPushButton(t("dlg_close_nothing"))
        for b in (self.restartButton, self.rebootButton, self.noActionButton):
            row.addWidget(b)
        layout.addLayout(row)
        self.restartButton.clicked.connect(lambda: self.done(1))
        self.rebootButton.clicked.connect(lambda: self.done(2))
        self.noActionButton.clicked.connect(lambda: self.done(0))

class NPIInfoDialog(QtWidgets.QDialog):
    """Show the driver-side override settings the JSON can't reach."""
    def __init__(self, parent=None):
        super().__init__(parent)
        t = getattr(parent, "_t", None) or (lambda k, **kw: k)
        self.setWindowTitle(t("npi_title"))
        self.resize(720, 420)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(t("npi_intro")))
        table = QtWidgets.QTableWidget(len(NPI_INFO), 3, self)
        table.setHorizontalHeaderLabels([t("npi_col_id"), t("npi_col_name"), t("npi_col_values")])
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        for r, (sid, name, vals) in enumerate(NPI_INFO):
            for c, txt in enumerate((sid, name, vals)):
                item = QtWidgets.QTableWidgetItem(txt)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        layout.addWidget(table)
        btns = QtWidgets.QHBoxLayout()
        open_btn = QtWidgets.QPushButton(t("npi_open_btn"))
        open_btn.clicked.connect(lambda: webbrowser.open(NPI_RELEASES_URL))
        close_btn = QtWidgets.QPushButton(t("npi_close_btn"))
        close_btn.clicked.connect(self.accept)
        btns.addWidget(open_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        layout.addLayout(btns)

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class DLSSOverrideApp(QtWidgets.QMainWindow):
    APP_VERSION = "2.4"
    TESTED_AGAINST_NVAPP = "11.0.7"

    def __init__(self):
        super().__init__()
        self.current_lang = "PT"
        self.resize(1180, 760)
        icon_path = resource_path("itg.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QtGui.QIcon(icon_path))
        self.session_processed = False
        self.key_checkboxes = {}
        self.setup_ui()
        self.apply_dark_theme()
        self.retranslate_ui()
        self.update_file_status()
        self._log_environment()
        self._auto_fill_sl_version()

    def _t(self, key, **kwargs):
        """Translate a string by key into the current language."""
        s = LANG[self.current_lang].get(key, key)
        return s.format(**kwargs) if kwargs else s

    def set_language(self, lang):
        if lang == self.current_lang:
            return
        self.current_lang = lang
        self.retranslate_ui()
        self.log(self._t("lang_switch_log"))

    # -- UI ------------------------------------------------------------------
    def setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)

        # Language toggle row (flag buttons, top-right)
        lang_row = QtWidgets.QHBoxLayout()
        lang_row.addStretch()
        self.pt_button = QtWidgets.QPushButton("🇧🇷  PT")
        self.pt_button.setMaximumWidth(70)
        self.pt_button.setMinimumHeight(28)
        self.pt_button.setObjectName("flagButton")
        self.pt_button.clicked.connect(lambda: self.set_language("PT"))
        self.en_button = QtWidgets.QPushButton("🇺🇸  EN")
        self.en_button.setMaximumWidth(70)
        self.en_button.setMinimumHeight(28)
        self.en_button.setObjectName("flagButton")
        self.en_button.clicked.connect(lambda: self.set_language("EN"))
        lang_row.addWidget(self.pt_button)
        lang_row.addWidget(self.en_button)
        root.addLayout(lang_row)

        # File path
        path_row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        username = getpass.getuser()
        default_path = fr"C:\Users\{username}\AppData\Local\NVIDIA Corporation\NVIDIA app\NvBackend\ApplicationStorage.json"
        self.path_edit.setText(default_path)
        self.path_edit.textChanged.connect(self.update_file_status)
        path_row.addWidget(self.path_edit)
        self.browse_button = QtWidgets.QPushButton("Browse")
        self.browse_button.clicked.connect(self.browse_file)
        path_row.addWidget(self.browse_button)
        root.addLayout(path_row)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setStyleSheet("padding: 5px; border-radius: 3px;")
        root.addWidget(self.status_label)

        # Per-key toggles
        self.keys_group = QtWidgets.QGroupBox()
        kg_layout = QtWidgets.QGridLayout(self.keys_group)
        for i, (key, spec) in enumerate(KEY_SPECS.items()):
            cb = QtWidgets.QCheckBox()  # label + tooltip set by retranslate_ui
            cb.setChecked(spec["default"])
            self.key_checkboxes[key] = cb
            kg_layout.addWidget(cb, i // 2, i % 2)
        root.addWidget(self.keys_group)

        # Extra options
        self.extra_group = QtWidgets.QGroupBox()
        eg = QtWidgets.QGridLayout(self.extra_group)

        self.bump_sl_cb = QtWidgets.QCheckBox()
        self.bump_sl_cb.setChecked(False)
        self.sl_version_edit = QtWidgets.QLineEdit(DEFAULT_LATEST_SL_VERSION)
        self.sl_version_edit.setMaximumWidth(90)
        self.scan_sl_btn = QtWidgets.QPushButton()
        self.scan_sl_btn.clicked.connect(self.scan_sl_action)
        eg.addWidget(self.bump_sl_cb, 0, 0)
        eg.addWidget(self.sl_version_edit, 0, 1)
        eg.addWidget(self.scan_sl_btn, 0, 2)

        self.sl_help_label = QtWidgets.QLabel()
        self.sl_help_label.setStyleSheet("color: #888; font-size: 11px; padding-left: 22px;")
        self.sl_help_label.setWordWrap(True)
        eg.addWidget(self.sl_help_label, 1, 0, 1, 3)

        self.patch_fp_cb = QtWidgets.QCheckBox()
        self.patch_fp_cb.setChecked(True)
        eg.addWidget(self.patch_fp_cb, 2, 0, 1, 3)

        self.readonly_checkbox = QtWidgets.QCheckBox()
        self.readonly_checkbox.setChecked(True)
        eg.addWidget(self.readonly_checkbox, 3, 0, 1, 3)

        self.dlss_indicator_cb = QtWidgets.QCheckBox()
        self.dlss_indicator_cb.setChecked(False)
        eg.addWidget(self.dlss_indicator_cb, 4, 0, 1, 3)

        root.addWidget(self.extra_group)

        # Primary action buttons
        btn_row = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton("Preview")
        self.preview_button.clicked.connect(self.preview_changes)
        self.preview_button.setMinimumHeight(35)
        btn_row.addWidget(self.preview_button)

        self.process_button = QtWidgets.QPushButton("Process File")
        self.process_button.clicked.connect(self.process_file)
        self.process_button.setMinimumHeight(35)
        btn_row.addWidget(self.process_button)

        self.revert_button = QtWidgets.QPushButton("Revert to Backup")
        self.revert_button.clicked.connect(self.revert_file_action)
        self.revert_button.setMinimumHeight(35)
        btn_row.addWidget(self.revert_button)
        root.addLayout(btn_row)

        # Utility row
        util = QtWidgets.QHBoxLayout()
        self.toggle_readonly_button = QtWidgets.QPushButton("Toggle Read-Only")
        self.toggle_readonly_button.clicked.connect(self.toggle_readonly)
        util.addWidget(self.toggle_readonly_button)

        self.restart_services_button = QtWidgets.QPushButton("Restart NVIDIA Services")
        self.restart_services_button.clicked.connect(self.restart_services_action)
        util.addWidget(self.restart_services_button)

        self.npi_button = QtWidgets.QPushButton("Driver-side overrides (NPI)")
        self.npi_button.clicked.connect(self.show_npi_info)
        util.addWidget(self.npi_button)

        self.clear_log_button = QtWidgets.QPushButton("Clear Log")
        self.clear_log_button.clicked.connect(self.clear_log)
        util.addWidget(self.clear_log_button)
        root.addLayout(util)

        # Log + donation sidebar (horizontal split)
        bottom_row = QtWidgets.QHBoxLayout()

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QtGui.QFont("Consolas", 9))
        bottom_row.addWidget(self.log_text, stretch=3)

        # Donation sidebar
        donate_panel = QtWidgets.QFrame()
        donate_panel.setObjectName("donatePanel")
        donate_panel.setMinimumWidth(220)
        donate_panel.setMaximumWidth(240)
        dp_layout = QtWidgets.QVBoxLayout(donate_panel)
        dp_layout.setSpacing(8)
        dp_layout.setContentsMargins(12, 10, 12, 10)

        self.donate_title_label = QtWidgets.QLabel()
        self.donate_title_label.setObjectName("donateTitle")
        self.donate_title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        dp_layout.addWidget(self.donate_title_label)

        self.donate_subtitle_label = QtWidgets.QLabel()
        self.donate_subtitle_label.setObjectName("donateSubtitle")
        self.donate_subtitle_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.donate_subtitle_label.setWordWrap(True)
        dp_layout.addWidget(self.donate_subtitle_label)

        # PIX QR
        qr_label = QtWidgets.QLabel()
        qr_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        qr_path = resource_path("qr_pix.png")
        if os.path.exists(qr_path):
            pixmap = QtGui.QPixmap(qr_path).scaled(
                170, 170,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation)
            qr_label.setPixmap(pixmap)
            qr_label.setStyleSheet("background: white; padding: 6px; border-radius: 4px;")
        dp_layout.addWidget(qr_label)

        pix_caption = QtWidgets.QLabel("🇧🇷 PIX")
        pix_caption.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        pix_caption.setStyleSheet("color: #aaa; font-size: 11px;")
        dp_layout.addWidget(pix_caption)

        self.copy_pix_btn = QtWidgets.QPushButton()
        self.copy_pix_btn.setObjectName("donatePix")
        self.copy_pix_btn.clicked.connect(lambda: self._copy_to_clipboard(DONATE_PIX_KEY, self.copy_pix_btn, "donate_pix"))
        dp_layout.addWidget(self.copy_pix_btn)

        self.copy_bep20_btn = QtWidgets.QPushButton()
        self.copy_bep20_btn.setObjectName("donateBep")
        self.copy_bep20_btn.clicked.connect(lambda: self._copy_to_clipboard(DONATE_BEP20_ADDR, self.copy_bep20_btn, "donate_bep20"))
        dp_layout.addWidget(self.copy_bep20_btn)

        self.paypal_btn = QtWidgets.QPushButton()
        self.paypal_btn.setObjectName("donatePaypal")
        self.paypal_btn.clicked.connect(lambda: webbrowser.open(DONATE_PAYPAL_URL))
        dp_layout.addWidget(self.paypal_btn)

        dp_layout.addStretch()

        # ITG branding at bottom of sidebar
        itg_logo = QtWidgets.QLabel()
        itg_logo.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        logo_path = resource_path("itg.png")
        if os.path.exists(logo_path):
            logo_pix = QtGui.QPixmap(logo_path).scaled(
                40, 40,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation)
            itg_logo.setPixmap(logo_pix)
        dp_layout.addWidget(itg_logo)
        itg_caption = QtWidgets.QLabel("by ITG")
        itg_caption.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        itg_caption.setStyleSheet("color: #666; font-size: 10px;")
        dp_layout.addWidget(itg_caption)

        bottom_row.addWidget(donate_panel)
        root.addLayout(bottom_row)

        self.log(self._t("log_init", v=self.APP_VERSION))
        self.log(self._t("log_target", p=default_path))

    def _copy_to_clipboard(self, text, btn, original_key):
        QtWidgets.QApplication.clipboard().setText(text)
        btn.setText(self._t("copied"))
        QtCore.QTimer.singleShot(1500, lambda: btn.setText(self._t(original_key)))

    def retranslate_ui(self):
        """Apply current language to every visible string AND every tooltip."""
        self.setWindowTitle(self._t("window_title", v=self.APP_VERSION))
        # Flags
        self.pt_button.setToolTip(self._t("tip_pt_btn"))
        self.en_button.setToolTip(self._t("tip_en_btn"))
        # Path row
        self.path_edit.setToolTip(self._t("tip_path"))
        self.browse_button.setText(self._t("browse"))
        self.browse_button.setToolTip(self._t("tip_browse"))
        # Group titles
        self.keys_group.setTitle(self._t("keys_group"))
        self.extra_group.setTitle(self._t("extra_group"))
        # Per-game checkbox label + tooltip (uses spec abbr -> tip_XX / key_XX_label)
        for key, spec in KEY_SPECS.items():
            cb = self.key_checkboxes.get(key)
            if cb is not None:
                slug = spec["abbr"].replace("-", "_")
                cb.setText(self._t(f"key_{slug}_label"))
                cb.setToolTip(self._t(f"tip_{slug}"))
        # Streamline SDK row
        self.bump_sl_cb.setText(self._t("sl_label"))
        self.bump_sl_cb.setToolTip(self._t("tip_sl_cb"))
        self.sl_version_edit.setToolTip(self._t("tip_sl_edit"))
        self.scan_sl_btn.setText(self._t("sl_scan"))
        self.scan_sl_btn.setToolTip(self._t("tip_sl_scan"))
        self.sl_help_label.setText(self._t("sl_help"))
        # Extra checkboxes
        self.patch_fp_cb.setText(self._t("patch_fp"))
        self.patch_fp_cb.setToolTip(self._t("tip_patch_fp"))
        self.readonly_checkbox.setText(self._t("set_ro"))
        self.readonly_checkbox.setToolTip(self._t("tip_readonly_cb"))
        self.dlss_indicator_cb.setText(self._t("dlss_indicator"))
        self.dlss_indicator_cb.setToolTip(self._t("tip_dlss_indicator"))
        # Action buttons
        self.preview_button.setText(self._t("preview"))
        self.preview_button.setToolTip(self._t("tip_preview"))
        self.process_button.setText(self._t("process"))
        self.process_button.setToolTip(self._t("tip_process"))
        self.revert_button.setText(self._t("revert"))
        self.revert_button.setToolTip(self._t("tip_revert"))
        self.restart_services_button.setText(self._t("restart_svc"))
        self.restart_services_button.setToolTip(self._t("tip_restart_svc"))
        self.npi_button.setText(self._t("npi_btn"))
        self.npi_button.setToolTip(self._t("tip_npi_btn"))
        self.clear_log_button.setText(self._t("clear_log"))
        self.clear_log_button.setToolTip(self._t("tip_clear_log"))
        # Donation panel
        self.donate_title_label.setText(self._t("donate_title"))
        self.donate_subtitle_label.setText(self._t("donate_subtitle"))
        self.copy_pix_btn.setText(self._t("donate_pix"))
        self.copy_pix_btn.setToolTip(self._t("tip_donate_pix"))
        self.copy_bep20_btn.setText(self._t("donate_bep20"))
        self.copy_bep20_btn.setToolTip(self._t("tip_donate_bep20"))
        self.paypal_btn.setText(self._t("donate_paypal"))
        self.paypal_btn.setToolTip(self._t("tip_donate_paypal"))
        # Read-only toggle button text+tooltip depends on current state
        self.update_file_status()

    def apply_dark_theme(self):
        style = """
        QWidget { background-color: #1e1e1e; color: #e0e0e0; font-family: "Segoe UI", sans-serif; }
        QLineEdit, QTextEdit { background-color: #2d2d30; border: 1px solid #3e3e42;
                               padding: 5px; border-radius: 3px; color: #e0e0e0; }
        QPushButton { background-color: #007ACC; border: none; padding: 6px 12px;
                      border-radius: 4px; color: #ffffff; font-weight: bold; }
        QPushButton:hover { background-color: #005A9E; }
        QPushButton:pressed { background-color: #003F73; }
        QPushButton#toggleReadonly { background-color: #6B4C9A; }
        QPushButton#toggleReadonly:hover { background-color: #553C7A; }
        QPushButton#restartServices { background-color: #CA5100; }
        QPushButton#restartServices:hover { background-color: #A34100; }
        QPushButton#npiButton { background-color: #2A7A2A; }
        QPushButton#npiButton:hover { background-color: #1E5C1E; }
        QPushButton#flagButton { background-color: #2d2d30; border: 1px solid #444; padding: 3px 8px;
                                 font-size: 12px; font-weight: 600; }
        QPushButton#flagButton:hover { background-color: #3a3a3e; border-color: #007ACC; }
        QPushButton#donatePix { background-color: #32BC9B; }
        QPushButton#donatePix:hover { background-color: #259678; }
        QPushButton#donateBep { background-color: #F0B90B; color: #1a1a1a; }
        QPushButton#donateBep:hover { background-color: #C49808; }
        QPushButton#donatePaypal { background-color: #003087; }
        QPushButton#donatePaypal:hover { background-color: #00227A; }
        QFrame#donatePanel { background-color: #232323; border: 1px solid #383838; border-radius: 6px; }
        QLabel#donateTitle { color: #ffb86c; font-size: 14px; font-weight: 700; }
        QLabel#donateSubtitle { color: #888; font-size: 11px; }
        QCheckBox { spacing: 5px; }
        QCheckBox::indicator { width: 16px; height: 16px; }
        QCheckBox::indicator:unchecked { border: 1px solid #555; background-color: #2d2d30; }
        QCheckBox::indicator:checked  { border: 1px solid #007ACC; background-color: #007ACC; }
        QGroupBox { border: 1px solid #3e3e42; border-radius: 4px; margin-top: 10px; padding-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        QTableWidget { background-color: #2d2d30; gridline-color: #3e3e42; }
        QHeaderView::section { background-color: #2d2d30; padding: 4px; border: 1px solid #3e3e42; }
        """
        self.setStyleSheet(style)
        self.toggle_readonly_button.setObjectName("toggleReadonly")
        self.restart_services_button.setObjectName("restartServices")
        self.npi_button.setObjectName("npiButton")

    # -- Logging -------------------------------------------------------------
    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_log(self):
        self.log_text.clear()
        self.log("Log cleared")

    def _log_environment(self):
        version = detect_nvidia_app_version()
        if version:
            self.log(self._t("log_nvapp", v=version))
            if not version.startswith(self.TESTED_AGAINST_NVAPP):
                self.log(self._t("log_note_untested", v=self.TESTED_AGAINST_NVAPP))
        gpu = detect_gpu_generation()
        if gpu:
            self.log(self._t("log_gpu", g=gpu))
            if gpu != "RTX 50":
                self.log(self._t("log_note_mfg", g=gpu))

    # -- File status ---------------------------------------------------------
    def update_file_status(self):
        file_path = self.path_edit.text().strip()
        if not os.path.exists(file_path):
            self.status_label.setText(self._t("status_not_found"))
            self.status_label.setStyleSheet(
                "background-color: #5a1d1d; color: #ff6b6b; padding: 5px; border-radius: 3px;")
            return
        readonly = is_read_only(file_path)
        if readonly:
            self.status_label.setText(self._t("status_readonly"))
            self.status_label.setStyleSheet(
                "background-color: #1d3a5a; color: #6bb3ff; padding: 5px; border-radius: 3px;")
            self.toggle_readonly_button.setText(self._t("make_rw"))
            self.toggle_readonly_button.setToolTip(self._t("tip_make_rw"))
        else:
            self.status_label.setText(self._t("status_writable"))
            self.status_label.setStyleSheet(
                "background-color: #3a5a1d; color: #a3ff6b; padding: 5px; border-radius: 3px;")
            self.toggle_readonly_button.setText(self._t("make_ro"))
            self.toggle_readonly_button.setToolTip(self._t("tip_make_ro"))

    def browse_file(self):
        current_path = self.path_edit.text().strip()
        initial_dir = os.path.dirname(current_path) if os.path.exists(current_path) else ""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, self._t("dlg_browse_title"), initial_dir,
            "JSON Files (*.json);;All Files (*)")
        if file_path:
            self.path_edit.setText(file_path)
            self.log(self._t("log_selected_file", p=file_path))

    def toggle_readonly(self):
        file_path = self.path_edit.text().strip()
        if not os.path.exists(file_path):
            QtWidgets.QMessageBox.critical(self, self._t("dlg_error_title"),
                                           self._t("dlg_error_file_not_found", p=file_path))
            return
        if is_read_only(file_path):
            self.log(self._t("log_removing_ro"))
            set_read_only(file_path, False, self.log)
            self.log(self._t("log_can_add_games"))
        else:
            self.log(self._t("log_setting_ro"))
            set_read_only(file_path, True, self.log)
            self.log(self._t("log_protected"))
        self.update_file_status()

    def restart_services_action(self):
        reply = QtWidgets.QMessageBox.question(
            self, self._t("dlg_restart_title"), self._t("dlg_restart_msg"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            restart_services(self.log)

    def show_npi_info(self):
        NPIInfoDialog(self).exec()

    def scan_sl_action(self):
        path = self.path_edit.text().strip()
        if not os.path.exists(path):
            self.log("ERROR: file not found, can't scan PinnedSLVersion")
            return
        v = scan_max_sl_version(path)
        if v:
            self.sl_version_edit.setText(v)
            self.log(f"Max PinnedSLVersion in file: {v}")
        else:
            self.log("No PinnedSLVersion entries found in file")

    def _auto_fill_sl_version(self):
        """On startup, pre-fill the SL version field with the max already in the file."""
        path = self.path_edit.text().strip()
        if not os.path.exists(path):
            return
        try:
            v = scan_max_sl_version(path)
            if v:
                self.sl_version_edit.setText(v)
                self.log(self._t("log_sl_detected", v=v))
        except Exception:
            pass

    def _enabled_keys(self):
        return {k for k, cb in self.key_checkboxes.items() if cb.isChecked()}

    def _pinned_sl_choice(self):
        if not self.bump_sl_cb.isChecked():
            return None
        v = self.sl_version_edit.text().strip()
        return v if v else None

    # -- Preview / Process / Revert -----------------------------------------
    def preview_changes(self):
        path = self.path_edit.text().strip()
        if not os.path.exists(path):
            QtWidgets.QMessageBox.critical(self, self._t("dlg_error_title"),
                                           self._t("dlg_error_file_not_found", p=path))
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, self._t("dlg_error_title"),
                                           self._t("dlg_error_read_json", e=str(e)))
            return
        enabled = self._enabled_keys()
        sl = self._pinned_sl_choice()
        rows = []
        apps = data.get("Applications", [])
        for entry in apps:
            app = entry.get("Application", {}) if isinstance(entry, dict) else {}
            name = app.get("DisplayName") or app.get("ShortName") or entry.get("LocalId") or "Unknown"
            changes = []
            for k in enabled:
                if k in app and app[k] != KEY_SPECS[k]["target"]:
                    changes.append(KEY_SPECS[k]["abbr"])
            if sl and "PinnedSLVersion" in app and app["PinnedSLVersion"] != sl:
                changes.append(f"SL {app['PinnedSLVersion']}->{sl}")
            if changes:
                rows.append((str(name), ", ".join(changes)))
        self.log(f"--- Preview: {len(rows)} of {len(apps)} app(s) will change ---")
        for name, ch in rows:
            self.log(f"  {name}: {ch}")
        if not rows:
            self.log("  (nothing to change)")

    def process_file(self):
        file_path = self.path_edit.text().strip()
        if not os.path.exists(file_path):
            QtWidgets.QMessageBox.critical(self, self._t("dlg_error_title"),
                                           self._t("dlg_error_file_not_found", p=file_path))
            return
        enabled = self._enabled_keys()
        if not enabled and not self.bump_sl_cb.isChecked():
            QtWidgets.QMessageBox.warning(self, self._t("dlg_nothing_title"),
                                          self._t("dlg_nothing_msg"))
            return
        sl_extra = self._t("dlg_process_sl_extra") if self.bump_sl_cb.isChecked() else ""
        reply = QtWidgets.QMessageBox.question(
            self, self._t("dlg_process_title"),
            self._t("dlg_process_msg", n=len(enabled), sl=sl_extra, p=file_path),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            self.log(self._t("log_op_cancelled"))
            return

        self.log("=" * 50)
        self.log(self._t("log_starting_process"))
        modified, _, _ = modify_file(file_path, enabled, self._pinned_sl_choice(), self.log)

        if self.patch_fp_cb.isChecked():
            fp_path = fingerprint_path_for(file_path)
            self.log("--- fingerprint.db ---")
            patch_fingerprint_db(fp_path, enabled, self.log)

        if self.dlss_indicator_cb.isChecked():
            self.log("--- NGX registry ---")
            set_dlss_indicator(True, self.log)

        if modified:
            self.session_processed = True
            if self.readonly_checkbox.isChecked():
                set_read_only(file_path, True, self.log)

        self.update_file_status()
        self.log("=" * 50)

    def revert_file_action(self):
        file_path = self.path_edit.text().strip()
        if not os.path.exists(file_path):
            QtWidgets.QMessageBox.critical(self, self._t("dlg_error_title"),
                                           self._t("dlg_error_file_not_found", p=file_path))
            return
        reply = QtWidgets.QMessageBox.question(
            self, self._t("dlg_revert_title"),
            self._t("dlg_revert_msg", p=file_path),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            self.log(self._t("log_revert_cancelled"))
            return
        self.log("=" * 50)
        self.log(self._t("log_starting_revert"))
        if revert_file(file_path, self.log):
            self.session_processed = False
        # Also offer to restore fingerprint.db if backup exists
        fp_path = fingerprint_path_for(file_path)
        fp_backup = fp_path + ".backup"
        if os.path.exists(fp_backup):
            try:
                make_writable(fp_path)
                shutil.copy2(fp_backup, fp_path)
                self.log(f"fingerprint.db restored from backup")
            except Exception as e:
                self.log(f"WARNING: fingerprint.db restore failed: {e}")
        self.update_file_status()
        self.log("=" * 50)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.session_processed:
            dialog = CloseActionDialog(self)
            result = dialog.exec()
            if result == 1:
                restart_services(self.log)
            elif result == 2:
                confirm = QtWidgets.QMessageBox.question(
                    self, self._t("dlg_reboot_confirm_title"),
                    self._t("dlg_reboot_confirm_msg"),
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
                if confirm == QtWidgets.QMessageBox.StandardButton.Yes:
                    subprocess.Popen(["shutdown", "/r", "/t", "10"],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        event.accept()

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = DLSSOverrideApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
