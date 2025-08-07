# print_project_files.py
import os
import re
import argparse

def get_project_structure(root_dir, file_regex, exclude_dirs=None, output_file=None):
    """
    遍历项目目录，匹配文件，并将文件路径和内容整合输出。

    :param root_dir: 项目的根目录路径。
    :param file_regex: 用于匹配文件名的正则表达式。
    :param exclude_dirs: 需要排除的目录列表。
    :param output_file: (可选) 输出结果的文件路径。
    """
    if exclude_dirs is None:
        exclude_dirs = []
    
    # 转换为集合以提高查找效率
    exclude_set = set(exclude_dirs)
    
    # 编译正则表达式以提高效率
    try:
        compiled_regex = re.compile(file_regex)
    except re.error as e:
        print(f"Error: 正则表达式 '{file_regex}' 无效: {e}")
        return

    # 准备输出
    output_lines = []

    for root, dirs, files in os.walk(root_dir, topdown=True):
        # --- 核心优化：原地修改dirs列表，阻止os.walk进入排除的目录 ---
        
        # 原始的 dirs[:] = [d for d in dirs if d not in exclude_set] 只能排除顶级目录
        # 我们需要更强大的排除逻辑
        
        # 过滤掉需要排除的目录
        dirs_to_remove = set()
        for d in dirs:
            # 检查绝对/相对路径是否以排除项开头
            dir_path = os.path.join(root, d)
            relative_dir_path = os.path.relpath(dir_path, root_dir).replace(os.sep, '/') # 标准化为 / 分隔符
            
            if d in exclude_set or relative_dir_path in exclude_set:
                dirs_to_remove.add(d)
        
        dirs[:] = [d for d in dirs if d not in dirs_to_remove]

        # 过滤掉需要排除的文件
        files_to_process = []
        for filename in files:
            file_path = os.path.join(root, filename)
            relative_file_path = os.path.relpath(file_path, root_dir).replace(os.sep, '/')
            
            if filename not in exclude_set and relative_file_path not in exclude_set:
                files_to_process.append(filename)

        for filename in files_to_process: # 只遍历过滤后的文件
            if compiled_regex.search(filename):
                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, root_dir)

                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 格式化输出
                    output_lines.append(f"--- File: {relative_path.replace(os.sep, '/')} ---")
                    output_lines.append(content)
                    output_lines.append("\n" * 2) # 添加一些空行以便分隔

                except Exception as e:
                    output_lines.append(f"--- File: {relative_path.replace(os.sep, '/')} ---")
                    output_lines.append(f"!!! Error reading file: {e} !!!")
                    output_lines.append("\n" * 2)

    final_output = "\n".join(output_lines)

    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_output)
            print(f"项目代码已成功整合到文件: {output_file}")
        except Exception as e:
            print(f"Error: 无法写入到文件 {output_file}: {e}")
    else:
        # 如果不指定输出文件，则直接打印到控制台
        print(final_output)

def main():
    parser = argparse.ArgumentParser(
        description="根据正则表达式抓取项目文件内容，并整合输出。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "root_dir",
        help="要扫描的项目根目录路径。"
    )
    parser.add_argument(
        "file_regex",
        help="用于匹配文件名的正则表达式。示例: '\\.(vue|ts|js)$'"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_file",
        help="将结果保存到的输出文件名。 (例如: project_context.txt)"
    )
    parser.add_argument(
        "-e", "--exclude",
        dest="exclude_dirs",
        default="node_modules,.git,dist,build,public/assets,pnpm-lock.yaml",
        help="需要排除的目录或文件名, 用逗号分隔。\n默认值: 'node_modules,.git,dist,build,public/assets,pnpm-lock.yaml'"
    )

    args = parser.parse_args()
    
    # 将逗号分隔的字符串转换为列表
    exclude_list = [item.strip() for item in args.exclude_dirs.split(',')]
    
    get_project_structure(args.root_dir, args.file_regex, exclude_list, args.output_file)

if __name__ == "__main__":
    main()