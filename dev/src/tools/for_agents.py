# Tools for AVA
from __future__ import annotations
import unicodedata
import os
from agents import function_tool

from tools.gmail import get_gmail_service
from email.message import EmailMessage
import base64
from googleapiclient.errors import HttpError


@function_tool
def read_dir_struct(directory_path: str) -> str:
    """Read the contents of a directory and return it in markdown format.
    
    Args:
        directory_path (str): The path to the directory to read, relative to the current directory.
                            Defaults to the current directory.
    
    Returns:
        str: The directory structure in markdown format.
    
    Raises:
        FileNotFoundError: If the directory does not exist.
        NotADirectoryError: If the path is not a directory.
    """
    # Define directories to ignore
    IGNORED_DIRS = {
        'venv',          # Python virtual environment
        'ava-env',           # Alternative virtual environment name
        '.env',          # Environment directory
        '.config',          # config directory
        '__pycache__',   # Python cache directories
        '.pytest_cache',  # Pytest cache
        '.mypy_cache',   # MyPy cache
    }
    
    def _list_directory(path: str, prefix: str = "") -> str:
        result = []
        try:
            # Get all items in the directory
            items = os.listdir(path)
            
            # Sort items (directories first, then files), filtering out ignored directories
            dirs = sorted([
                item for item in items 
                if os.path.isdir(os.path.join(path, item)) 
                and item not in IGNORED_DIRS
            ])
            files = sorted([
                item for item in items 
                if os.path.isfile(os.path.join(path, item))
            ])
            
            # Process directories
            for d in dirs:
                full_path = os.path.join(path, d)
                result.append(f"{prefix}- {d}/")
                # Recursively list subdirectory contents
                result.append(_list_directory(full_path, prefix + "  "))
                
            # Process files
            for f in files:
                result.append(f"{prefix}- {f}")
                
        except PermissionError:
            result.append(f"{prefix}- ermission denied")
        except Exception as e:
            result.append(f"{prefix}- Error: {str(e)}")
            
        return "\n".join(result)
    
    if not os.path.exists(directory_path):
        raise FileNotFoundError(f"Directory not found: {directory_path}")
    if not os.path.isdir(directory_path):
        raise NotADirectoryError(f"Not a directory: {directory_path}")
    
    return _list_directory(directory_path)


@function_tool
def read_file_contents(file_path: str) -> str:
    """Read the contents of any file from the current directory: txt, csv, etc...
    
    Args:
        file_path (str): The path to the file to read, relative to the current directory.
    
    Returns:
        str: The contents of the specified file.
    
    Raises:
        FileNotFoundError: If the file does not exist.
    """
    with open(file_path, "r", encoding="utf-8", errors="strict") as f:
        text = f.read()
    return unicodedata.normalize("NFC", text)


@function_tool
def read_file_contents(file_path: str) -> str:
    """Read the contents of any file from the current directory: txt, csv, etc...
    
    Args:
        file_path (str): The path to the file to read, relative to the current directory.
    
    Returns:
        str: The contents of the specified file.
    
    Raises:
        FileNotFoundError: If the file does not exist.
    """
    with open(file_path, "r", encoding="utf-8", errors="strict") as f:
        text = f.read()
    return unicodedata.normalize("NFC", text)
    
    
@function_tool
def create_new_file(file_path: str, content: str = "") -> str:
    """Create a new file at the specified path with optional content.
    
    Args:
        file_path (str): The path where the new file should be created, relative to the current directory.
        content (str): Optional initial content to write to the file. Defaults to empty string.
    
    Returns:
        str: A message confirming the file creation.
    
    Raises:
        FileExistsError: If the file already exists at the specified path.
        OSError: If there are permission issues or the directory doesn't exist.
    """
    # Ensure the directory exists
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    
    # Check if file already exists to avoid overwriting
    if os.path.exists(file_path):
        raise FileExistsError(f"File already exists at: {file_path}")
    
    # Create the file with the specified content
    with open(file_path, "w") as file:
        file.write(content)
    
    return f"File successfully created at: {file_path}"

@function_tool  
def overwrite_existing_file(file_path: str, content: str) -> str:
    """Overwrite the contents of an existing file at the specified path.
    
    Args:
        file_path (str): The path to the file to update, relative to the current directory.
        content (str): The content to write to the file.
    
    Returns:
        str: A message confirming the file update.
    
    Raises:
        FileNotFoundError: If the file does not exist at the specified path.            
    """
    with open(file_path, "w") as file:
        file.write(content)
    
    return f"File successfully updated at: {file_path}"

@function_tool
def write_email_draft(recipient_email: str, subject: str, body: str):
    """Create a draft email using the Gmail API.
    
    Args:
        recipient (str): The email address of the recipient.
        subject (str): The subject line of the email.
        body (str): The main content/body of the email.
    
    Returns:
        dict or None: A dictionary containing the draft information including 'id' and 'message' 
                     if successful, None if an error occurs.
    
    Raises:
        HttpError: If there is an error communicating with the Gmail API.
        
    Note:
        This function requires:
        - Gmail API credentials to be properly configured
        - USER_EMAIL environment variable to be set with the sender's email address
        - Appropriate Gmail API permissions for creating drafts
    """
    try:
        # create gmail api client
        service = get_gmail_service()

        message = EmailMessage()

        message.set_content(body)

        message["To"] = recipient_email
        message["From"] = os.getenv("USER_EMAIL")
        message["Subject"] = subject

        # encoded message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        create_message = {"message": {"raw": encoded_message}}
        # pylint: disable=E1101
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body=create_message)
            .execute()
        )

        print(f'Draft id: {draft["id"]}\nDraft message: {draft["message"]}')

    except HttpError as error:
        print(f"An error occurred: {error}")
        draft = None

    return draft

@function_tool
def json(status: str,
                         final: str,
                         message: str,
                         data: str,
                         ask: str,
                         error: str,
                        ) -> dict:
    """Génère et valide l'objet de résultat final structuré pour l'agent Exécuteur.

    Cet outil est utilisé comme dernière étape du processus afin de produire un
    résultat normalisé décrivant ce que l'Exécuteur a fait : son statut, un message
    lisible, les données structurées éventuelles, ainsi que les questions de suivi
    ou erreurs si nécessaire.

    Arguments :
        status (str) :
            Statut de l'exécution. Doit être l'une des valeurs suivantes :
            - "completed" : la tâche a été exécutée avec succès.
            - "need_info" : la tâche n'a pas pu être terminée faute d'informations.
            - "error" : la tâche a échoué suite à une erreur non récupérable.

        final (str) :
            Indicateur exprimé en chaîne ("True" ou "False") précisant s'il s'agit
            d'un résultat final.

        message (str) :
            Réponse complète, auto-suffisante avec détails de la demande initiale.

        data (str) :
            Représentation textuelle d'un dictionnaire contenant les données
            structurées produites pendant l'exécution, ou "None" s'il n'y en a pas.

        ask (str) :
            Question de suivi à poser si des informations supplémentaires sont
            nécessaires (uniquement lorsque status == "need_info"), sinon "None".

        error (str) :
            Description courte de l'erreur si status == "error", sinon "None".

    Retour :
        str : Un string contenant une forme de dictionnaire avec exactement les clés suivantes :
            {
                "status": str,
                "final": str,
                "message": str,
                "data": str,
                "ask": str,
                "error": str
            }

    Exceptions :
        ValueError : Levée si un argument sort des valeurs autorisées ou si
        la combinaison fournie n'est pas cohérente (par exemple : status="completed"
        mais error ≠ "None").

    """
    if status not in {"completed", "need_info", "error"}:
        raise ValueError(f"Invalid status value: '{status}'")

    if final not in {"True", "False"}:
        raise ValueError(f"Invalid final value: '{final}'")

    if status == "completed":
        if error != "None":
            raise ValueError("Inconsistent result: status='completed' but error is not 'None'.")
        if ask != "None":
            raise ValueError("Inconsistent result: status='completed' but ask is not 'None'.")

    if status == "need_info":
        if ask == "None":
            raise ValueError("Inconsistent result: status='need_info' but ask is 'None'.")
        if error != "None":
            raise ValueError("Inconsistent result: status='need_info' but error is not 'None'.")

    if status == "error":
        if error == "None":
            raise ValueError("Inconsistent result: status='error' but error is 'None'.")
        if ask != "None":
            raise ValueError("Inconsistent result: status='error' but ask is not 'None'.")

    return str({
        "status": status,
        "final": final,
        "message": message,
        "data": data,
        "ask": ask,
        "error": error,
    })

