import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import pymysql
from bm_up_video import *
import os

# 数据库配置
db_config = {
    'host': 'sh-cynosdbmysql-grp-pbl95cyg.sql.tencentcdb.com',
    'port': 23593,
    'user': 'root',
    'password': 'Junzhun123',
    'database': 'video_auto',
    'charset': 'utf8mb4'
}

# 数据库操作封装
def insert_bm_info(bm_id, bm_token, bm_note):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    sql = "INSERT INTO bm_info (bm_id, bm_token, bm_note) VALUES (%s, %s, %s)"
    cursor.execute(sql, (bm_id, bm_token, bm_note))
    conn.commit()
    cursor.close()
    conn.close()

def fetch_bm_notes():
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    sql = "SELECT id, bm_note FROM bm_info"
    cursor.execute(sql)
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results

def fetch_bm_detail(bm_id):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    sql = "SELECT bm_id, bm_token, bm_note FROM bm_info WHERE id = %s"
    cursor.execute(sql, (bm_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result

# 主应用类
class BMApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BM 信息管理")
        self.root.geometry("800x700")

        # 创建菜单按钮
        self.menu_frame = tk.Frame(self.root)
        self.menu_frame.pack(side="left", fill="y")

        self.content_frame = tk.Frame(self.root, bg="white")
        self.content_frame.pack(side="right", fill="both", expand=True)

        self.menu_buttons = [
            ("添加 BM", self.show_add_bm_page),
            ("查看 BM", self.show_bm_list_page)
        ]

        for name, callback in self.menu_buttons:
            btn = tk.Button(self.menu_frame, text=name, width=20, command=callback)
            btn.pack(pady=5)

        self.show_add_bm_page()

    def clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def show_add_bm_page(self):
        self.clear_content()
        tk.Label(self.content_frame, text="BM-ID：").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        bm_id_entry = tk.Entry(self.content_frame, width=40)
        bm_id_entry.grid(row=0, column=1)

        tk.Label(self.content_frame, text="BM-token：").grid(row=1, column=0, padx=10, pady=10, sticky="e")
        bm_token_entry = tk.Entry(self.content_frame, width=40)
        bm_token_entry.grid(row=1, column=1)

        tk.Label(self.content_frame, text="BM-备注信息：").grid(row=2, column=0, padx=10, pady=10, sticky="e")
        bm_note_entry = tk.Entry(self.content_frame, width=40)
        bm_note_entry.grid(row=2, column=1)

        def submit():
            insert_bm_info(bm_id_entry.get(), bm_token_entry.get(), bm_note_entry.get())
            messagebox.showinfo("成功", "BM 信息已添加")
            bm_id_entry.delete(0, tk.END)
            bm_token_entry.delete(0, tk.END)
            bm_note_entry.delete(0, tk.END)

        submit_btn = tk.Button(self.content_frame, text="添加", command=submit)
        submit_btn.grid(row=3, column=0, columnspan=2, pady=20)

    def show_bm_list_page(self):
        self.clear_content()
        tk.Label(self.content_frame, text="BM 备注列表", font=("Arial", 12)).pack(pady=10)

        tree_frame = tk.Frame(self.content_frame)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree = ttk.Treeview(tree_frame, columns=("id", "note"), show="headings", height=10)
        tree.heading("id", text="ID")
        tree.heading("note", text="备注信息")
        tree.column("id", anchor="center", width=80)
        tree.column("note", anchor="center", width=300)
        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        for row in fetch_bm_notes():
            tree.insert("", "end", values=row)

        def view_selected_detail():
            selected = tree.selection()
            if selected:
                bm_id = tree.item(selected[0])["values"][0]
                detail = fetch_bm_detail(bm_id)
                if detail:
                    self.show_bm_detail_page(detail)

        detail_button = tk.Button(self.content_frame, text="查看详情", command=view_selected_detail, bg="#4CAF50", fg="white", width=15)
        detail_button.pack(pady=10)

    def show_bm_detail_page(self, detail):
        self.clear_content()
        # 调用 API 获取返回数据
        result = get_bm_folders_nested(detail[0], detail[1])

        tk.Label(self.content_frame, text="BM 详情信息", font=("Arial", 14)).pack(pady=10)
        tk.Label(self.content_frame, text=f"BM-ID：{detail[0]}", anchor="w", width=60).pack(pady=5)
        tk.Label(self.content_frame, text=f"BM-Token：{detail[1]}", anchor="w", width=60).pack(pady=5)
        tk.Label(self.content_frame, text=f"备注信息：{detail[2]}", anchor="w", width=60).pack(pady=5)

        # 结果列表
        tk.Label(self.content_frame, text="返回结果", font=("Arial", 12)).pack(pady=10)
        frame = tk.Frame(self.content_frame)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree = ttk.Treeview(
            frame,
            columns=("id", "full_path"),
            show="tree headings",  # 树 + 列标题
            height=10
        )
        tree.heading("#0", text="名称")
        tree.column("#0", anchor="w", width=200)

        tree.heading("id", text="ID")
        tree.column("id", anchor="w", width=150)
        tree.heading("full_path", text="路径")
        tree.column("full_path", anchor="w", width=250)

        tree.pack(side="left", fill="both", expand=True)
        # 添加滚动条
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

        # 插入层级数据
        if isinstance(result, list):
            for folder in result:
                # 插入一级节点：parent=""，text=名称，values 对应 id 和 full_path
                parent_node = tree.insert(
                    "", "end",
                    text=folder["name"],
                    values=(folder["id"], folder["full_path"])
                )
                # 插入子节点：parent=parent_node
                for sub in folder.get("data", []):
                    tree.insert(
                        parent_node, "end",
                        text=sub["name"],
                        values=(sub["id"], sub["full_path"])
                    )

        # 创建子文件夹功能
        def create_subfolder():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("警告", "请先选择一个主文件夹！")
                return
            parent_folder_id = tree.item(sel[0])['values'][0]  # 获取主文件夹的 ID
            parent_name = tree.item(sel[0])['values'][1]
            def submit_subfolder_name():
                subfolder_name = entry.get().strip()
                if not subfolder_name:
                    messagebox.showwarning("提示", "请输入子文件夹名称")
                    return
                # 调用函数创建子文件夹
                create_subfolder_api(subfolder_name, parent_folder_id, detail[0], detail[1],parent_name)
                dialog.destroy()

            dialog = tk.Toplevel(self.root)
            dialog.title("创建子文件夹")
            dialog.geometry("300x120")
            tk.Label(dialog, text="请输入子文件夹名称：").pack(pady=10)
            entry = tk.Entry(dialog, width=30)
            entry.pack(pady=5)
            tk.Button(dialog, text="创建", command=submit_subfolder_name, bg="#4CAF50", fg="white").pack(pady=10)

        # 上传选择文件夹，先获取所选行 key
        def upload_folder():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("警告", "请先选择一个文件夹！")
                return
            folder_id = tree.item(sel[0])['values'][0]  # 假设 value 列为 folder id
            directory = filedialog.askdirectory(title="选择本地文件夹")
            if directory:
                for root, dirs, files in os.walk(directory):
                    for f in files:
                        if f.lower().endswith('.mp4'):
                            path = os.path.join(root, f)
                            upload_video_to_bm_library(path, detail[0], detail[1], folder_id, f)
                messagebox.showinfo("完成", "批量上传完成！")

        # 创建文件夹的弹窗函数
        def open_create_folder_dialog():
            def submit_folder_name():
                folder_name = entry.get().strip()
                if not folder_name:
                    messagebox.showwarning("提示", "请输入文件夹名称")
                    return
                create_folder(folder_name, detail[0], detail[1])
                dialog.destroy()

            dialog = tk.Toplevel(self.root)
            dialog.title("创建素材文件夹")
            dialog.geometry("300x120")
            tk.Label(dialog, text="请输入文件夹名称：").pack(pady=10)
            entry = tk.Entry(dialog, width=30)
            entry.pack(pady=5)
            tk.Button(dialog, text="创建", command=submit_folder_name, bg="#4CAF50", fg="white").pack(pady=10)

        tk.Button(self.content_frame, text="上传素材到选中文件夹", bg="#4CAF50", fg="white",
                  command=upload_folder).pack(pady=10)
        tk.Button(self.content_frame, text="创建文件夹", bg="#4CAF50", fg="white",
                  command=open_create_folder_dialog).pack(pady=10)
        tk.Button(self.content_frame, text="创建子文件夹", bg="#4CAF50", fg="white",
                  command=create_subfolder).pack(pady=10)  # 创建子文件夹按钮

        # 返回
        tk.Button(self.content_frame, text="返回列表", bg="#2196F3", fg="white",
                  command=self.show_bm_list_page).pack(pady=20)

    # 创建子文件夹的 API 调用函数
    def create_subfolder_api(subfolder_name, parent_folder_id, business_id, access_token):
        url = f"https://graph.facebook.com/v22.0/{parent_folder_id}/subfolders"
        params = {
            'access_token': access_token,
            'name': subfolder_name  # 子文件夹的名称
        }
        response = requests.post(url, params=params)
        data = response.json()
        if 'id' in data:
            messagebox.showinfo("成功", f"子文件夹 '{subfolder_name}' 创建成功！")
        else:
            messagebox.showerror("错误", f"子文件夹创建失败: {data.get('error', {}).get('message', '未知错误')}")
if __name__ == "__main__":
    root = tk.Tk()
    app = BMApp(root)
    root.mainloop()
