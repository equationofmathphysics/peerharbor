#!/usr/bin/env python3
"""Opt-in input target for an isolated virtual X11 display. Closes automatically after five minutes."""
import argparse
import json
import os
from pathlib import Path
import tkinter as tk

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--display', required=True, help='独立测试用 X11 显示，不能是当前桌面')
args = parser.parse_args()
if args.display == os.environ.get('DISPLAY'):
    parser.error('请使用独立虚拟显示，避免干扰本机桌面。')
os.environ['DISPLAY'] = args.display
output = Path(__file__).resolve().parent/'artifacts/isolated-x11-input.json'
root = tk.Tk()
root.title('Remote Console Input Check')
root.configure(bg='#101c2d')
root.overrideredirect(True)
root.geometry('1280x800+0+0')
root.after(300_000, root.destroy)
clicks = 0
text = tk.StringVar()
result = tk.StringVar(value='Waiting for input through the remote browser')

def save(*_):
    output.write_text(json.dumps({'kind':'isolated X11 test window', 'display':args.display, 'typed_text':text.get(), 'clicks':clicks}, indent=2)+'\n')

def confirm():
    global clicks
    clicks += 1
    result.set(f'Input received: {text.get()} | Button clicks: {clicks}')
    save()

panel = tk.Frame(root, bg='#101c2d')
panel.place(relx=.5, rely=.5, anchor='center')
tk.Label(panel, text='X11 INPUT TEST', fg='#78e3cf', bg='#101c2d', font=('DejaVu Sans',36,'bold')).pack(pady=20)
tk.Label(panel, text='Remote keyboard and mouse verification', fg='white', bg='#101c2d', font=('DejaVu Sans',24)).pack(pady=12)
tk.Label(panel, text='Type in this box, then click Verify input', fg='#b5c4db', bg='#101c2d', font=('DejaVu Sans',20)).pack(pady=12)
entry = tk.Entry(panel, textvariable=text, width=38, font=('DejaVu Sans',28), bg='#f2f6fa', fg='#102030')
entry.pack(pady=24, ipady=10)
tk.Button(panel, text='Verify input', command=confirm, font=('DejaVu Sans',24), bg='#78e3cf', fg='#102030').pack(pady=20, ipadx=25, ipady=8)
tk.Label(panel, textvariable=result, fg='#dce8f5', bg='#101c2d', font=('DejaVu Sans',20)).pack(pady=20)
tk.Button(panel, text='Close test window', command=root.destroy, font=('DejaVu Sans',16)).pack(pady=20)
text.trace_add('write', save)
save()
root.mainloop()
