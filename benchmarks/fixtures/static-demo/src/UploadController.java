package demo;

import org.springframework.web.multipart.MultipartFile;

public class UploadController {
    public String uploadAvatar(MultipartFile file, String originalFilename) throws Exception {
        String target = "/tmp/upload/" + originalFilename;
        file.transferTo(new java.io.File(target));
        return target;
    }
}
