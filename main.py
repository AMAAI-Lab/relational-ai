import os
from dotenv import load_dotenv
import logging
import sys
import asyncio
import httpx
import time  # Add time module
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeAllGroupChats
from telegram.constants import ChatAction
from telegram.ext import filters, MessageHandler, ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, CallbackContext, Application
from collections import defaultdict
from copy import deepcopy
import json
import telegram
from prompts import (
    DRIVER_PROMPT,
    ANALYZER_PROMPT_TEMPLATE,
    PHASE_PROMPTS,
    ANALYZER_TEMPLATES
)
import re
from datetime import datetime
import os

# Message logging function
def log_message_to_file(chat_id, user_id, message_type, content, additional_info=None):
    """
    Log messages to a separate file for review
    
    Args:
        chat_id: The chat ID where the message occurred
        user_id: The user ID (for user messages) or 'BOT' for bot messages
        message_type: Type of message ('USER_MESSAGE', 'BOT_RESPONSE', 'BUTTON_CLICK', 'COMMAND', etc.)
        content: The actual message content
        additional_info: Any additional context information
    """
    try:
        # Create logs directory if it doesn't exist
        if not os.path.exists('message_logs'):
            os.makedirs('message_logs')
        
        # Create filename based on date and chat_id
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f'message_logs/chat_{chat_id}_{date_str}.log'
        
        # Format timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Create log entry
        log_entry = f"[{timestamp}] CHAT:{chat_id} | USER:{user_id} | TYPE:{message_type}\n"
        log_entry += f"CONTENT: {content}\n"
        
        if additional_info:
            log_entry += f"INFO: {additional_info}\n"
        
        log_entry += "-" * 80 + "\n\n"
        
        # Write to file
        with open(filename, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
    except Exception as e:
        print(f"Error logging message: {e}")

def log_clean_conversation(chat_id, user_id, content, is_bot=False):
    """
    Log only the conversation content in a clean format
    Format: Echo: message or User_01: message or User_02: message
    
    Args:
        chat_id: The chat ID where the message occurred
        user_id: The user ID (ignored if is_bot=True)
        content: The actual message content
        is_bot: True if this is a bot message, False if user message
    """
    try:
        # Create logs directory if it doesn't exist
        if not os.path.exists('message_logs'):
            os.makedirs('message_logs')
        
        # Create filename for clean log
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f'message_logs/chat_{chat_id}_{date_str}_clean.log'
        
        # Determine speaker label
        if is_bot:
            speaker = "Echo"
        else:
            # Get user slot (User_01 or User_02)
            user_slot = get_or_create_user_slot(chat_id, user_id)
            speaker = user_slot if user_slot else f"User_{user_id}"
        
        # Create clean log entry
        log_entry = f"{speaker}: {content}\n\n"
        
        # Write to file
        with open(filename, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
    except Exception as e:
        print(f"Error logging clean conversation: {e}")

#chatbot stuff
chat_histories = defaultdict(list)
current_phase = defaultdict(lambda: 1)  # Default phase is 1
response_question = "NIL"
structured_summary = ""
firsttime = True
newphase = False
full_chat_history = []
full_analyzed_summary = []  # Change to list to store each phase's summary
currentphase = 0
previous_message_data = "NULL"
first_message_id = ""
firstmesaage = True
bot_message_id =  10000000000000
phasechat = 0
messages_since_last_bot = []  # Track messages since last bot response
turn_summary = {}  # Initialize empty turn summary
user_mapping = {}  # Maps chat_id to {telegram_id: user_slot} dictionary

# Add this global variable near other globals
chat_busy_flags = defaultdict(lambda: False)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Hide httpx logs but keep other logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

is_last_message = False

# Replace the existing prompts with imported ones
currentphaseprompt = PHASE_PROMPTS
current_analyzer_phase = ANALYZER_TEMPLATES
general_response_prompts = DRIVER_PROMPT

# Add after other imports and before global variables
def clean_json_output(output):
    """Clean the analyzer output to ensure it's only valid JSON."""
    try:
        # Find the first '{' and last '}'
        start = output.find('{')
        end = output.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = output[start:end]
            # Verify it's valid JSON
            json.loads(json_str)  # Just to validate
            return json_str
        return "{}"
    except json.JSONDecodeError:
        print("\033[91mError: Could not extract valid JSON from analyzer output\033[0m")
        return "{}"

def merge_json_summaries(current_summary, new_analysis):
    """
    Merge new analysis into current summary, updating only non-empty fields
    """
    try:
        # Convert string inputs to dict if needed
        if isinstance(current_summary, str):
            current_summary = json.loads(current_summary)
        if isinstance(new_analysis, str):
            new_analysis = json.loads(new_analysis)
        
        # Ensure we have dictionaries to work with
        if not current_summary or not isinstance(current_summary, dict):
            current_summary = {}
        if not new_analysis or not isinstance(new_analysis, dict):
            return current_summary
            
        # For each field in new analysis
        for key, new_value in new_analysis.items():
            if key not in current_summary:
                current_summary[key] = new_value
            elif isinstance(new_value, dict) and isinstance(current_summary[key], dict):
                # Recursively merge nested dictionaries
                for sub_key, sub_value in new_value.items():
                    if sub_key not in current_summary[key] or (isinstance(sub_value, str) and sub_value.strip() != ""):
                        current_summary[key][sub_key] = sub_value
            elif isinstance(new_value, str) and new_value.strip() != "":
                # Update if new value is non-empty string
                current_summary[key] = new_value
                
        return current_summary
    except json.JSONDecodeError as e:
        print("\033[91mError decoding JSON in merge_json_summaries:\033[0m", e)
        return current_summary or {}
    except Exception as e:
        print("\033[91mError in merge_json_summaries:\033[0m", e)
        return current_summary or {}

async def chat_driver_response(driver_prompt, chat_id, user_id):
    max_retries = 2  # Reduced from 3
    retry_delay = 0.5  # Reduced from 1 second
    start_time = time.time()

    # Create messages array with full chat history
    messages = [{'role': 'system', 'content': driver_prompt}]
    messages.extend(chat_histories[chat_id])  # Add all messages including bot responses

    # Print driver input in cyan color
    #print("\033[96m=== DRIVER INPUT ===\033[0m")
    #for msg in messages:
        #print("\033[96m" + f"  {msg['role']}: {msg['content']}" + "\033[0m")
    #print("\033[96m=== END DRIVER INPUT ===\033[0m")

    for attempt in range(max_retries):
        try:
            api_start_time = time.time()
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:  # Reduced timeouts
                response = await client.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers={
                        'Authorization': os.getenv('OPENAI_API_KEY'), # This is the API key for the OpenAI API
                        'Content-Type': 'application/json'
                    },
                    json={
                        'model': os.getenv('API_MODEL'), # This is the model we are using for the driver response
                        'messages': messages,
                        'temperature': 0.7
                    }
                )
                api_end_time = time.time()
                # print(f"\033[93mAPI call took: {api_end_time - api_start_time:.2f} seconds\033[0m")
                
                if response.status_code == 200:
                    response_data = response.json()
                    bot_response = response_data['choices'][0]['message']['content']
                    chat_histories[chat_id].append({'role': 'assistant', 'content': bot_response})
                    end_time = time.time()
                    # print(f"\033[93mTotal driver response time: {end_time - start_time:.2f} seconds\033[0m")
                    return bot_response
                else:
                    logging.error(f"Failed to get response from OpenAI: {response.text}")
                    
        except (httpx.TimeoutException, httpx.ConnectTimeout) as e:
            if attempt == max_retries - 1:  # Last attempt
                logging.error(f"All retries failed: {str(e)}")
                return "I'm having connection issues. Please try again in a moment."
            await asyncio.sleep(retry_delay * (attempt + 1))  # Shorter backoff
            continue
            
        except Exception as e:
            logging.error(f"Unexpected error in chat_driver_response: {str(e)}")
            return "Something unexpected happened. Please try again."

    return "I'm having trouble connecting. Please try again."

async def chat_analyzer_response(analyzer_prompt, chat_id, user_id):
    max_retries = 2  # Reduced from 3
    retry_delay = 0.5  # Reduced from 1 second
    start_time = time.time()

    for attempt in range(max_retries):
        try:
            api_start_time = time.time()
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:  # Reduced timeouts
                response = await client.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers={
                        'Authorization': os.getenv('OPENAI_API_KEY'), # This is the API key for the OpenAI API
                        'Content-Type': 'application/json'
                    },
                    json={
                        'model': os.getenv('API_MODEL'), # This is the model we are using for the driver response
                        'messages': [
                            {'role': 'system', 'content': analyzer_prompt},
                            *chat_histories[chat_id][-3:]  # Only send last 3 messages instead of 5
                        ],
                        'temperature': 0.2
                    }
                )
                api_end_time = time.time()
                # print(f"\033[93mAnalyzer API call took: {api_end_time - api_start_time:.2f} seconds\033[0m")
                
                if response.status_code == 200:
                    response_data = response.json()
                    end_time = time.time()
                    # print(f"\033[93mTotal analyzer response time: {end_time - start_time:.2f} seconds\033[0m")
                    return response_data['choices'][0]['message']['content']
                else:
                    logging.error(f"Failed to get response from OpenAI: {response.text}")
                    
        except (httpx.TimeoutException, httpx.ConnectTimeout) as e:
            if attempt == max_retries - 1:  # Last attempt
                logging.error(f"All retries failed: {str(e)}")
                return "{}"  # Return empty JSON on all retries failed
            await asyncio.sleep(retry_delay * (attempt + 1))  # Shorter backoff
            continue
            
        except Exception as e:
            logging.error(f"Unexpected error in chat_analyzer_response: {str(e)}")
            return "{}"  # Return empty JSON on error

    return "{}"  # Return empty JSON if all retries fail

async def button(update: Update, context: CallbackContext) -> None:
    try:
        global previous_message_data
        global response_question
        global is_last_message
        user_id = update.callback_query.from_user.id
        chat_id = update.callback_query.message.chat.id
        messages = update.callback_query.message

        # Log the button click
        log_message_to_file(
            chat_id=chat_id,
            user_id=user_id,
            message_type="BUTTON_CLICK",
            content="Continue button clicked",
            additional_info=f"Callback data: {update.callback_query.data}"
        )

        # --- BUSY FLAG CHECK ---
        if chat_busy_flags[chat_id]:
            print(f"[BUSY] Ignoring button for chat {chat_id} because it's still processing.")
            return
        chat_busy_flags[chat_id] = True

        # Immediately send "..." to show the bot is thinking
        thinking_message = await context.bot.send_message(
            chat_id=chat_id,
            text="..."
        )

        if previous_message_data != "NULL":
            try:
                # Remove button from the previous message
                await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=previous_message_data.message_id,
                    reply_markup=None
                )
            except telegram.error.BadRequest as e:
                if "Message is not modified" not in str(e):
                    print(f"Error removing previous button: {e}")
            except telegram.error.TimedOut:
                print("Timeout removing previous button")
            except Exception as e:
                print(f"Error removing previous button: {e}")

        await phaseprompting(update, context, chat_id, user_id, messages, thinking_message)

        if is_last_message:
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
            except telegram.error.BadRequest as e:
                if "Message is not modified" not in str(e):
                    print(f"Error removing last message button: {e}")
            except telegram.error.TimedOut:
                print("Timeout removing last message button")
            except Exception as e:
                print(f"Error removing last message button: {e}")
                
    except Exception as e:
        logging.error(f"Error in button handler: {str(e)}")
        # Reset response_question to force generation of new response instead of repeating old one
        global response_question
        response_question = "NIL"
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Sorry, I encountered an error. Please try again."
            )
    finally:
        chat_busy_flags[chat_id] = False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global response_question
    global structured_summary
    global count
    global firsttime
    global newphase
    global currentphase
    global analyze
    global full_analyzed_summary
    global firstmesaage
    global first_message_id
    global bot_message_id
    global phasechat
    global messages_since_last_bot
    edit_message = False

    # Get chat_id first
    if update.callback_query:
        chat_id = update.callback_query.from_user.id
    else:
        chat_id = update.effective_chat.id

    # --- BUSY FLAG CHECK ---
    if chat_busy_flags[chat_id]:
        print(f"[BUSY] Ignoring message for chat {chat_id} because it's still processing.")
        return
    chat_busy_flags[chat_id] = True
    try:
        message = update.message or update.edited_message
        if not message:
            chat_busy_flags[chat_id] = False
            return  # Exit if no valid message

        user_id = message.from_user.id
        user_message = message.text
        
        # Log the incoming user message
        log_message_to_file(
            chat_id=chat_id,
            user_id=user_id,
            message_type="USER_MESSAGE" if not edit_message else "EDITED_MESSAGE",
            content=user_message,
            additional_info=f"Chat type: {message.chat.type}, Message ID: {message.message_id}"
        )
        
        # Skip command messages
        if user_message and user_message.startswith('/'):
            log_message_to_file(
                chat_id=chat_id,
                user_id=user_id,
                message_type="COMMAND",
                content=user_message,
                additional_info="Command message - skipped processing"
            )
            return
            
        user_slot = get_or_create_user_slot(chat_id, user_id)  # Get consistent user slot

        # Log clean conversation (only for non-command messages)
        if user_message and not user_message.startswith('/'):
            log_clean_conversation(
                chat_id=chat_id,
                user_id=user_id,
                content=user_message,
                is_bot=False
            )

        if update.edited_message:
            edit_message = True
            message_id = message.message_id
            print("Edited message id", message_id)

        # Store the previous turn's messages before updating chat_histories
        messages_since_last_bot = chat_histories[chat_id][-2:] if len(chat_histories[chat_id]) >= 2 else chat_histories[chat_id]

        # To edit the dictionary before it is send to chat
        if edit_message:
            before_or_after_botmessage = int(message_id)-int(bot_message_id)
            if before_or_after_botmessage >= 0 or bot_message_id==10000000000000:
                annotated_message = f"User {user_id} ({user_slot}): {user_message}"  # Include user slot in message
                
                # Find and replace the original message instead of using index calculation
                # Look for the original message in chat history and replace it
                found_original = False
                for i, msg in enumerate(chat_histories[chat_id]):
                    if msg.get('role') == 'user' and f"User {user_id}" in msg.get('content', ''):
                        # This is likely the original message, replace it
                        chat_histories[chat_id][i] = {'role': 'user', 'content': annotated_message}
                        found_original = True
                        break
                
                # If we couldn't find the original message, just append the edited version
                if not found_original:
                    chat_histories[chat_id].append({'role': 'user', 'content': annotated_message})
        else:
            annotated_message = f"User {user_id} ({user_slot}): {user_message}"  # Include user slot in message
            context_messages = chat_histories[chat_id]
            context_messages.append({'role': 'user', 'content': annotated_message})

        if firstmesaage:
            first_message_id = message.message_id
            firstmesaage = False

        should_respond = False

        # Determine if the bot should respond based on chat type and mention
        if message.chat.type == "private":
            should_respond = True
        elif message.entities:
            for entity in message.entities:
                if entity.type == MessageEntity.MENTION:
                    mention = message.text[entity.offset:entity.offset + entity.length]
                    if mention.lower() == os.getenv('TELEGRAM_BOT_NAME'):  # Using .lower() to make it case-insensitive
                        should_respond = True
                        break

        # If the bot is mentioned, process the response
        if should_respond:
            await phaseprompting(update, context, chat_id, user_id, message, None)
        else:
            logging.info(f"Logged in {message.chat.type} from user {user_id}: '{message.text}'")

    except Exception as e:
        logging.error(f"Error in handle_message: {str(e)}")
        # Reset response_question to force generation of new response instead of repeating old one
        global response_question
        response_question = "NIL"
        # You might want to send an error message to the user here
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Sorry, I encountered an error processing your message. Please try again."
            )
    finally:
        chat_busy_flags[chat_id] = False

def analzye(chat_id):
    global full_chat_history
    global context_messages
    global first_message_id
    global firstmesaage
    global phasechat
    full_chat_history += chat_histories[chat_id]
    print("\033[95m" + "This message means the bot is in the next phase" + "\033[0m")
    print("\033[95m" + "This is the chat messages: " + str(full_chat_history) + "\033[0m")

    chat_histories[chat_id] = []
    context_messages = []
    phasechat = 1
    firstmesaage = True

def prepare_structure_for_analyzer(structure):
    """Prepare the structure for analyzer by removing validity_check"""
    try:
        # If it's a string that looks like a JSON template, extract just the JSON part
        if isinstance(structure, str):
            start = structure.find('{')
            end = structure.rfind('}') + 1
            if start >= 0 and end > start:
                structure = structure[start:end]
            structure = json.loads(structure)
            
        if isinstance(structure, dict):
            # Remove validity_check field
            structure.pop('validity_check', None)
        return structure
    except Exception as e:
        print(f"\033[91mError preparing structure: {e}\033[0m")
        # Return a basic empty template instead of empty dict
        return {
            "phase": 0,
            "name": {
                "user_01": "",
                "user_02": ""
            },
            "recreational_activities": {
                "user_01": "",
                "user_02": ""
            },
            "fun_fact": {
                "user_01": "",
                "user_02": ""
            }
        }

def validate_analysis(analysis, phase_template):
    """
    Validate and clean analysis to ensure it follows the phase template structure
    phase_template: The template for the current phase (from all_analyzer_phase)
    """
    try:
        # Parse inputs
        data = json.loads(analysis) if isinstance(analysis, str) else analysis
        
        # If template is a string containing JSON template, extract just the JSON part
        if isinstance(phase_template, str):
            start = phase_template.find('{')
            end = phase_template.rfind('}') + 1
            if start >= 0 and end > start:
                phase_template = phase_template[start:end]
            template = json.loads(phase_template)
        else:
            template = phase_template
        
        # Start with template structure
        cleaned = deepcopy(template)
        
        # Only copy values that match template structure
        for key, value in data.items():
            if key in template:
                if isinstance(template[key], dict) and isinstance(value, dict):
                    # For nested dictionaries (like name, recreational_activities)
                    for sub_key, sub_value in value.items():
                        if sub_key in template[key] and isinstance(sub_value, str):
                            if not (sub_value.startswith('@') or sub_value.startswith('User') or sub_value.isdigit()):
                                cleaned[key][sub_key] = sub_value
                elif isinstance(template[key], str) and isinstance(value, str):
                    # For direct string values
                    if not (value.startswith('@') or value.startswith('User') or value.isdigit()):
                        cleaned[key] = value
        
        # Set validity_check based on whether we found meaningful data
        has_meaningful_data = False
        for key, value in cleaned.items():
            if key not in ['phase', 'validity_check']:
                if isinstance(value, dict) and any(v.strip() for v in value.values()):
                    has_meaningful_data = True
                    break
                elif isinstance(value, str) and value.strip():
                    has_meaningful_data = True
                    break
        
        cleaned['validity_check'] = "has_data" if has_meaningful_data else "no_data"
        return cleaned
        
    except Exception as e:
        print(f"\033[91mValidation error: {e}\033[0m")
        # Return a basic empty template if validation fails
        return {
            "phase": 0,
            "validity_check": "no_data",
            "name": {
                "user_01": "",
                "user_02": ""
            },
            "recreational_activities": {
                "user_01": "",
                "user_02": ""
            },
            "fun_fact": {
                "user_01": "",
                "user_02": ""
            }
        }

def split_message(message):
    """Split a message by newlines only. Each paragraph becomes a separate chunk.
    If the message ends with 'PHASE DONE', keep it attached to the last chunk."""
    # Step 1: Check for PHASE DONE at the end
    phase_done_marker = 'PHASE DONE'
    has_phase_done = message.rstrip().endswith(phase_done_marker)
    if has_phase_done:
        # Remove the marker temporarily
        message = message.rstrip()
        message = message[:-(len(phase_done_marker))].rstrip()
    
    # Step 2: Split by newlines only
    chunks = [p.strip() for p in message.split('\n') if p.strip()]
    
    # Step 3: Reattach PHASE DONE
    if has_phase_done and chunks:
        chunks[-1] = chunks[-1].rstrip() + ' ' + phase_done_marker
    elif has_phase_done:
        chunks.append(phase_done_marker)
    
    return chunks

def escape_markdown(text):
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def calculate_reading_delay(text_length):
    """
    Calculate appropriate delay based on text length for reading
    
    Formula:
    - Base delay: 1.5 seconds (minimum comfortable pause)
    - Reading time: length / 40 (characters per second, accounting for comfortable reading)
    - Maximum delay: 8 seconds (to avoid making users wait too long)
    """
    base_delay = 1.5
    reading_time = text_length / 40  # Comfortable reading speed
    total_delay = base_delay + reading_time
    
    # Cap at 8 seconds to stay within Telegram's typing indicator timeout
    return min(total_delay, 8.0)

def format_markdown(text):
    """Format text with MarkdownV2 syntax, handling bold text with **."""
    # First escape all special characters
    text = escape_markdown(text)
    
    # Then handle bold text (replace ** with * for MarkdownV2)
    text = text.replace('\\*\\*', '*')
    
    return text

async def send_message_safe(context, chat_id, text, reply_markup=None, message_id=None, is_edit=False):
    """
    Safely send or edit a message with MarkdownV2, falling back to plain text if parsing fails
    """
    try:
        # First try with MarkdownV2
        formatted_text = format_markdown(text)
        
        if is_edit:
            return await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=formatted_text,
                reply_markup=reply_markup,
                parse_mode='MarkdownV2'
            )
        else:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=formatted_text,
                reply_markup=reply_markup,
                parse_mode='MarkdownV2'
            )
            
    except telegram.error.BadRequest as e:
        if "can't parse entities" in str(e) or "can't find end of" in str(e):
            # Markdown parsing failed, try with plain text
            print(f"\033[93mMarkdown parsing failed, falling back to plain text: {e}\033[0m")
            try:
                if is_edit:
                    return await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,  # Use original text without formatting
                        reply_markup=reply_markup,
                        parse_mode=None  # No markdown
                    )
                else:
                    return await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,  # Use original text without formatting
                        reply_markup=reply_markup,
                        parse_mode=None  # No markdown
                    )
            except Exception as e2:
                print(f"\033[91mEven plain text failed: {e2}\033[0m")
                raise e2
        else:
            # Some other BadRequest error, re-raise
            raise e
    except Exception as e:
        # Any other error, re-raise
        raise e

async def send_unsplit_message(context, chat_id, message_text, add_button_to_last=False, existing_thinking_message=None):
    """
    Send a message without splitting it into parts - used when bot is repeating itself
    """
    start_time = time.time()
    
    # Log the bot response
    log_message_to_file(
        chat_id=chat_id,
        user_id="BOT",
        message_type="BOT_RESPONSE_REPEAT",
        content=message_text,
        additional_info=f"Sent as single message, Has button: {add_button_to_last}"
    )
    
    # Log clean conversation for bot response
    log_clean_conversation(
        chat_id=chat_id,
        user_id=None,  # Not used for bot messages
        content=message_text,
        is_bot=True
    )
    
    # Print bot response to console for visibility
    print(f"\033[92m=== BOT RESPONSE REPEAT (Chat {chat_id}) ===\033[0m")
    print(f"\033[92m{message_text}\033[0m")
    print(f"\033[92m=== END BOT RESPONSE REPEAT ===\033[0m")
    
    # Use existing thinking message or create a new one
    if existing_thinking_message:
        thinking_message = existing_thinking_message
    else:
        # Immediately send "..." to show the bot is thinking
        thinking_message = await context.bot.send_message(
            chat_id=chat_id,
            text="..."
        )
    
    # Format the message with MarkdownV2
    formatted_text = format_markdown(message_text)
    
    if add_button_to_last:
        keyboard = [[InlineKeyboardButton("Click here to continue the conversation :)", callback_data='sup')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Edit the thinking message with the full content and button
        message = await send_message_safe(
            context=context,
            chat_id=chat_id,
            text=message_text,
            reply_markup=reply_markup,
            message_id=thinking_message.message_id,
            is_edit=True
        )
        end_time = time.time()
        # print(f"\033[93mTotal unsplit message sending time: {end_time - start_time:.2f} seconds\033[0m")
        return message
    else:
        # Edit the thinking message with the full content (no button)
        await send_message_safe(
            context=context,
            chat_id=chat_id,
            text=message_text,
            message_id=thinking_message.message_id,
            is_edit=True
        )
        end_time = time.time()
        # print(f"\033[93mTotal unsplit message sending time: {end_time - start_time:.2f} seconds\033[0m")
        return None

async def send_split_message(context, chat_id, message_text, add_button_to_last=False, existing_thinking_message=None):
    start_time = time.time()
    
    # Log the bot response
    log_message_to_file(
        chat_id=chat_id,
        user_id="BOT",
        message_type="BOT_RESPONSE",
        content=message_text,
        additional_info=f"Split into parts: {len(split_message(message_text))}, Has button: {add_button_to_last}"
    )
    
    # Log clean conversation for bot response
    log_clean_conversation(
        chat_id=chat_id,
        user_id=None,  # Not used for bot messages
        content=message_text,
        is_bot=True
    )
    
    # Print bot response to console for visibility
    print(f"\033[92m=== BOT RESPONSE (Chat {chat_id}) ===\033[0m")
    print(f"\033[92m{message_text}\033[0m")
    print(f"\033[92m=== END BOT RESPONSE ===\033[0m")
    
    # Use existing thinking message or create a new one
    if existing_thinking_message:
        thinking_message = existing_thinking_message
    else:
        # Immediately send "..." to show the bot is thinking
        thinking_message = await context.bot.send_message(
            chat_id=chat_id,
            text="..."
        )
    
    parts = split_message(message_text)
    
    try:
        # Edit the "..." message with the first part
        if parts:
            send_start = time.time()
            await send_message_safe(
                context=context,
                chat_id=chat_id,
                text=parts[0],
                message_id=thinking_message.message_id,
                is_edit=True
            )
            send_end = time.time()
            # print(f"\033[93mFirst message edit time: {send_end - send_start:.2f} seconds\033[0m")
            
            # Refresh typing indicator immediately after first part
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            
            # Add delay after first part if there are more parts coming
            if len(parts) > 1:
                await asyncio.sleep(calculate_reading_delay(len(parts[0])))
        
        # Send remaining parts as separate messages
        for part in parts[1:-1]:  # All parts except first and last
            send_start = time.time()
            await send_message_safe(
                context=context,
                chat_id=chat_id,
                text=part
            )
            send_end = time.time()
            # print(f"\033[93mMessage send time: {send_end - send_start:.2f} seconds\033[0m")
            
            # Refresh typing indicator immediately after each part
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            
            # Add a natural pause between messages
            await asyncio.sleep(calculate_reading_delay(len(part)))
        
        # Handle the last part (if there are multiple parts)
        if len(parts) > 1:
            if add_button_to_last:
                keyboard = [[InlineKeyboardButton("Click here to continue the conversation :)", callback_data='sup')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                send_start = time.time()
                message = await send_message_safe(
                    context=context,
                    chat_id=chat_id,
                    text=parts[-1],
                    reply_markup=reply_markup
                )
                send_end = time.time()
                # print(f"\033[93mLast message send time: {send_end - send_start:.2f} seconds\033[0m")
                end_time = time.time()
                # print(f"\033[93mTotal message sending time: {end_time - start_time:.2f} seconds\033[0m")
                return message
            else:
                send_start = time.time()
                await send_message_safe(
                    context=context,
                    chat_id=chat_id,
                    text=parts[-1]
                )
                send_end = time.time()
                # print(f"\033[93mLast message send time: {send_end - send_start:.2f} seconds\033[0m")
                end_time = time.time()
                # print(f"\033[93mTotal message sending time: {end_time - start_time:.2f} seconds\033[0m")
                return None
        else:
            # Only one part - handle the button on the edited message
            if add_button_to_last:
                keyboard = [[InlineKeyboardButton("Click here to continue the conversation :)", callback_data='sup')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Edit the message again to add the button
                message = await send_message_safe(
                    context=context,
                    chat_id=chat_id,
                    text=parts[0],
                    reply_markup=reply_markup,
                    message_id=thinking_message.message_id,
                    is_edit=True
                )
                end_time = time.time()
                # print(f"\033[93mTotal message sending time: {end_time - start_time:.2f} seconds\033[0m")
                return message
            else:
                end_time = time.time()
                # print(f"\033[93mTotal message sending time: {end_time - start_time:.2f} seconds\033[0m")
                return None
    finally:
        # Cancel the typing indicator task only if we started one
        typing_task = None
        if typing_task:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

async def phase(update: Update, context: ContextTypes.DEFAULT_TYPE, currentphaseprompt, current_analyzer_phase, chat_id, user_id, message, thinking_message):
    global currentphase, structured_summary, full_analyzed_summary, response_question
    global previous_message_data, bot_message_id, phasedone

    # Initialize phase state
    phasedone = True
    dont_skip_message = True

    # Generate chatbot response using the accumulated analysis
    generate_response = (
        general_response_prompts + "\n" + 
        currentphaseprompt[currentphase] + 
        " \n Previous phase summaries: " + json.dumps(full_analyzed_summary, indent=2) +
        " \n Chat history of current phase so far: "
    )
    response_message = await chat_driver_response(generate_response, chat_id, user_id)
    response_question = response_message

    # Handle phase transitions
    if "goodbye" in response_message.lower():
        # Final phase - run analyzer one last time before saving
        analyzer_prompt = ANALYZER_PROMPT_TEMPLATE.format(
            previous_summaries=json.dumps(full_analyzed_summary, indent=2) if full_analyzed_summary else "[]",
            structure=current_analyzer_phase[currentphase]
        )
        
        # Use entire chat history for final analysis
        messages = [{'role': 'system', 'content': analyzer_prompt}]
        messages.extend(chat_histories[chat_id])  # Add all messages from current phase
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = await client.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': os.getenv('OPENAI_API_KEY'), # This is the API key for the OpenAI API
                        'Content-Type': 'application/json'
                    },
                    json={
                        'model': os.getenv('API_MODEL'), # This is the model we are using for the driver response
                    'messages': messages,
                    'temperature': 0.2
                }
            )
            if response.status_code == 200:
                analysis = response.json()['choices'][0]['message']['content']
                full_analyzed_summary.append(json.loads(analysis))

        # Print final bot message to console
        print(f"\033[92m=== FINAL BOT MESSAGE (Chat {chat_id}) ===\033[0m")
        print(f"\033[92m{response_message}\033[0m")
        print(f"\033[92m=== END FINAL MESSAGE ===\033[0m")
        
        await context.bot.send_message(chat_id=chat_id, text=response_message)
        
        # Conversation completed - gracefully shutdown
        print("\033[92mConversation completed successfully. Shutting down...\033[0m")
        await context.application.stop()
        await context.application.shutdown()
        return True

    elif "phase done" in response_message.lower():
        # Phase transition - run analyzer before transitioning
        analyzer_prompt = ANALYZER_PROMPT_TEMPLATE.format(
            previous_summaries=json.dumps(full_analyzed_summary, indent=2) if full_analyzed_summary else "[]",
            structure=current_analyzer_phase[currentphase]
        )
        
        # Use entire chat history for phase analysis
        messages = [{'role': 'system', 'content': analyzer_prompt}]
        messages.extend(chat_histories[chat_id])  # Add all messages from current phase
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = await client.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': os.getenv('OPENAI_API_KEY'), # This is the API key for the OpenAI API
                        'Content-Type': 'application/json'
                    },
                    json={
                        'model': os.getenv('API_MODEL'), # This is the model we are using for the driver response
                    'messages': messages,
                    'temperature': 0.2
                }
            )
            if response.status_code == 200:
                analysis = response.json()['choices'][0]['message']['content']
                full_analyzed_summary.append(json.loads(analysis))

        # Phase transition
        dont_skip_message = response_message.lower() != "phase done"
        edited_message = response_message.replace("PHASE DONE", "")

        print("\033[94mPHASE TRANSITION:\033[0m")
        print(f"Moving from phase {currentphase} to {currentphase + 1}")

        # Show typing indicator during phase transition
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # Send the final message of the current phase if needed
        if dont_skip_message and edited_message.strip():
            await send_split_message(context, chat_id, edited_message)

        # Preserve the current phase history before clearing it
        full_chat_history.extend(chat_histories[chat_id])
        chat_histories[chat_id] = []

        # Generate the first message of the new phase with clean history
        currentphase += 1
        generate_response = (
            general_response_prompts + "\n" + 
            currentphaseprompt[currentphase] + 
            " \n Previous phase summaries: " + json.dumps(full_analyzed_summary, indent=2) +
            " \n Chat history of current phase so far: "
        )
        next_phase_message = await chat_driver_response(generate_response, chat_id, user_id)
        response_question = next_phase_message

        # Start continuous typing indicator before sending new phase message
        # (Let send_split_message manage the typing indicator)
        previous_message_data = await send_split_message(
            context, 
            chat_id, 
            next_phase_message, 
            add_button_to_last=True
        )
        if previous_message_data:
            bot_message_id = previous_message_data.message_id
        
        return False

    else:
        # Continue current phase
        if phasedone:
            # Clean up previous button if it exists
            if previous_message_data != "NULL":
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=previous_message_data.message_id,
                        reply_markup=None
                    )
                except telegram.error.BadRequest as e:
                    if "Message is not modified" not in str(e):
                        print(f"Error removing previous button: {e}")
                except Exception as e:
                    print(f"Error removing previous button: {e}")
            
            # Send the response as multiple messages
            previous_message_data = await send_split_message(
                context,
                chat_id,
                response_message,
                add_button_to_last=True,
                existing_thinking_message=thinking_message
            )
            if previous_message_data:
                bot_message_id = previous_message_data.message_id
        
        return False

async def phaseprompting(update, context, chat_id, user_id, messages, thinking_message):
    """Main loop for handling phases"""
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    while True:
        # Run current phase
        phase_complete = await phase(
            update, context, 
            currentphaseprompt, current_analyzer_phase,
            chat_id, user_id, messages, thinking_message
        )
        
        # If phase didn't complete, wait for next user input
        if not phase_complete:
            break

        # If we're at the last phase, exit
        if currentphase >= len(currentphaseprompt):
            break

        # Small delay between phases
        #await asyncio.sleep(1)

def get_or_create_user_slot(chat_id, user_id):
    """Map a Telegram user ID to a consistent user slot (user_01 or user_02)"""
    if chat_id not in user_mapping:
        user_mapping[chat_id] = {}
    
    if user_id not in user_mapping[chat_id]:
        # If this is the first or second user in this chat
        if len(user_mapping[chat_id]) == 0:
            user_mapping[chat_id][user_id] = "user_01"
        elif len(user_mapping[chat_id]) == 1:
            user_mapping[chat_id][user_id] = "user_02"
    
    return user_mapping[chat_id].get(user_id)

# Add a set to track which chats have used /start
started_chats = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Log the start command
    log_message_to_file(
        chat_id=chat_id,
        user_id=user_id,
        message_type="START_COMMAND",
        content="/start command executed",
        additional_info=f"Chat type: {update.effective_chat.type}, First name: {update.effective_user.first_name}"
    )
    
    # Check if this chat has already started
    if chat_id in started_chats:
        await update.message.reply_text(
            "The conversation has already started. Use /continue to proceed with the conversation."
        )
        return
    
    # Add chat to started chats
    started_chats.add(chat_id)
    
    welcome_message = (
        "Welcome! 👋\n\n"
        "This is a space for you and your friend to chat, reflect, and share — with a little help from Echo, your conversation companion.\n\n"
        "Things will ease in gently, no pressure at all.\n\n"
        "Just a heads-up: Echo can only read text, so it won't be able to see any photos or stickers you send.\n\n"
        "When you're both ready, type /continue to begin."
    )
    await update.message.reply_text(welcome_message)
    
    # Update commands to only show continue
    commands = [BotCommand("continue", "Continue to the next turn")]
    await context.bot.set_my_commands(
        commands,
        scope=BotCommandScopeAllGroupChats()
    )
    await context.bot.set_my_commands(commands)  # Update default scope too

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = (
        "Here's how to use Remini:\n\n"
        "1. Use /start to begin a new conversation\n"
        "2. Follow the prompts and share your memories\n"
        "3. Use /continue to move to the next turn\n"
        "4. Use /pause if you need a break\n\n"
        "Remember, both users should participate in the conversation!"
    )
    await update.message.reply_text(help_text)

async def continue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Continue to the next turn when /continue is issued."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Clean up previous button if it exists
    global previous_message_data, chat_histories
    if previous_message_data != "NULL":
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=previous_message_data.message_id,
                reply_markup=None
            )
        except telegram.error.BadRequest as e:
            if "Message is not modified" not in str(e):
                print(f"Error removing previous button: {e}")
        except Exception as e:
            print(f"Error removing previous button: {e}")
    
    # Create a new message object without the command text
    message = update.message
    # Store the current chat history length
    current_history_len = len(chat_histories[chat_id])
    
    # Call phaseprompting
    await phaseprompting(update, context, chat_id, user_id, message, None)
    
    # Remove the command message from chat history if it was added
    if len(chat_histories[chat_id]) > current_history_len:
        chat_histories[chat_id].pop()  # Remove the last message if it was added

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause the conversation when /pause is issued."""
    await update.message.reply_text(
        "Taking a short break. When you're ready to continue, use /continue to proceed."
    )

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send information about the bot when /about is issued."""
    about_text = (
        "About Echo 🤖\n\n"
        "Echo is a chatbot created to help close friends or partners share things that don't always come up in everyday conversation — the kind of stuff that helps you feel seen, known, and a little more connected."
        "You'll be invited to explore three questions together. Each one goes a little deeper, giving you space to reflect, support each other, and maybe even discover something new about yourselves along the way.\n\n"
        "Created with ❤️ to help meaningful conversations feel natural — and just a little magical."
    )
    await update.message.reply_text(about_text)

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the conversation from a specific phase for testing purposes."""
    global currentphase, chat_histories, turn_summary, full_analyzed_summary, firstmesaage, first_message_id, phasechat
    
    # Check if a phase number was provided
    if not context.args:
        await update.message.reply_text(
            "Please specify a phase number. Usage: /test <phase_number>"
        )
        return
    
    try:
        # Get the requested phase number
        requested_phase = int(context.args[0])
        
        # Validate phase number
        if requested_phase < 1 or requested_phase > len(currentphaseprompt):
            await update.message.reply_text(
                f"Invalid phase number. Please choose a number between 1 and {len(currentphaseprompt)}."
            )
            return
        
        # Reset necessary variables
        chat_id = update.effective_chat.id
        chat_histories[chat_id] = []
        turn_summary = {}
        full_analyzed_summary = []
        firstmesaage = True
        first_message_id = ""
        phasechat = 0
        
        # Set the current phase (adjust for 0-based indexing)
        currentphase = requested_phase - 1
        
        # Generate initial message for the selected phase
        generate_response = (
            general_response_prompts + "\n" + 
            currentphaseprompt[currentphase] + 
            " \n Structured record of the current conversation: {} \n Chat history of current phase so far: "
        )
        response_message = await chat_driver_response(generate_response, chat_id, update.effective_user.id)
        
        # Send the initial message with continue button
        keyboard = [[InlineKeyboardButton("Click here when you're ready →", callback_data='sup')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        global previous_message_data, bot_message_id
        previous_message_data = await context.bot.send_message(
            chat_id=chat_id,
            text=f"Starting test from Phase {requested_phase}:\n\n{response_message}",
            reply_markup=reply_markup
        )
        bot_message_id = previous_message_data.message_id
        
        # Add the bot's message to chat history
        chat_histories[chat_id].append({
            'role': 'assistant',
            'content': response_message
        })
        
    except ValueError:
        await update.message.reply_text(
            "Please provide a valid number for the phase."
        )
    except Exception as e:
        logging.error(f"Error in test command: {str(e)}")
        # Reset response_question to force generation of new response instead of repeating old one
        global response_question
        response_question = "NIL"
        await update.message.reply_text(
            "oops — something glitched on my end while setting up the next part. mind trying again in a sec?"
        )

async def post_init(application: Application) -> None:
    """Post initialization hook to set up commands."""
    # Initially show both start and continue
    commands = [
        BotCommand("start", "Start a new conversation"),
        BotCommand("continue", "Continue to the next turn")
    ]
    
    # Set commands for all types of chats
    await application.bot.set_my_commands(commands)  # Default scope (all chats)
    
    # Explicitly set for group chats
    await application.bot.set_my_commands(
        commands,
        scope=BotCommandScopeAllGroupChats()
    )
    
    print("Bot commands have been set up!")

if __name__ == '__main__':
    # Build application
    application = (
        ApplicationBuilder()
        .token(os.getenv('TELEGRAM_TOKEN'))
        .read_timeout(60)
        .write_timeout(60)
        .post_init(post_init)
        .build()
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("continue", continue_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("test", test_command))  # Add the new test command handler

    # Add existing handlers
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)
    application.add_handler(CallbackQueryHandler(button))

    # Start the bot
    print("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)